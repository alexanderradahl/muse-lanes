// Muse lanes: tools to start/inspect/stop supervised `muse exec` runs, a panel listing them, and one wake-up per finished lane.
// Refuses to supervise anything itself: bin/muse-lane owns retries, stalls and acceptance, and survives this session.
// Wake-ups are exactly-once across sessions: the runner records owner_session per lane, and `ack` claims each announcement.
import { atom, read } from 'claude-code'
import type { Register } from 'claude-code'

import type { MuseLane as Lane } from '../types'

const PANE = 'muse-lanes'
const lanes = atom({ plugin: 'muse', key: 'lanes' } as const, [] as Lane[])
const triesRef = atom({ plugin: 'muse', key: 'summaryTries' } as const, {} as Record<string, number>)
const TERMINAL = new Set(['done', 'failed', 'gave_up', 'stopped'])
const POLL_MS = 20_000
const SUMMARY_TRIES = 3
let pollInFlight = false

const TOOLS = [
  {
    name: 'lane_start',
    description:
      'Start a supervised Muse lane: one or more steps run in sequence by `muse exec` (reasoning max by default) in `cwd`, ' +
      'retried with backoff for transient failures (stalls, timeouts, 429/5xx, network errors), once more for model failed/cancelled, ' +
      'never for auth or spawn failures, then the optional `accept` shell command. Use one step for an agent, ' +
      'several for a workflow. Returns the lane id at once; the session gets ONE prompt with the summary when the lane ends, so do not poll.',
    inputSchema: {
      type: 'object',
      required: ['cwd', 'steps'],
      properties: {
        cwd: { type: 'string', description: 'Absolute working directory (usually a worktree).' },
        steps: {
          type: 'array',
          minItems: 1,
          items: {
            type: 'object',
            properties: {
              brief: { type: 'string', description: 'Absolute path to a brief file.' },
              prompt: { type: 'string', description: 'Inline brief text (used when no brief path).' },
            },
          },
        },
        accept: { type: 'string', description: 'Acceptance shell command run in cwd after the last step.' },
        label: { type: 'string' },
        effort: { type: 'string', description: 'Reasoning effort, default max.' },
        stall_min: { type: 'number', description: 'Minutes of no log and no git change before a retry, default 40.' },
      },
    },
  },
  { name: 'lane_status', description: 'Muse lanes and their state (all, or one by id).', inputSchema: { type: 'object', properties: { id: { type: 'string' } } } },
  { name: 'lane_summary', description: "A finished lane's summary: attempts, commits, acceptance, each step's final answer.", inputSchema: { type: 'object', required: ['id'], properties: { id: { type: 'string' } } } },
  { name: 'lane_stop', description: 'Stop a running Muse lane.', inputSchema: { type: 'object', required: ['id'], properties: { id: { type: 'string' } } } },
  { name: 'lane_resume', description: 'Resume an orphaned lane (its supervisor died) from its recorded step.', inputSchema: { type: 'object', required: ['id'], properties: { id: { type: 'string' } } } },
]

async function lane($: any, args: string[], timeoutMs = 60_000) {
  const r = await $.process.run(['python3', `${$.plugin.root}/bin/muse-lane`, ...args], { timeoutMs })
  return { ok: r.exitCode === 0, code: r.exitCode as number, out: (r.stdout + (r.exitCode === 0 ? '' : `\n${r.stderr}`)).trim() }
}

async function answer($: any, args: string[]) {
  const r = await lane($, args, 30_000)
  void poll($)
  return r.ok ? { result: r.out || 'ok' } : { result: r.out, isError: true }
}

async function poll($: any) {
  if (pollInFlight) return
  pollInFlight = true
  try {
    const r = await lane($, ['status', '--json'])
    if (!r.ok) return
    let list: Lane[] = []
    try { list = JSON.parse(r.out) } catch { return }
    await $.state.set({ plugin: 'muse', key: 'lanes' }, list)

    let me: string
    try {
      me = await $.session.id()
    } catch {
      return
    }
    if (!me) return
    const tries = { ...((((await read($, triesRef)) as Record<string, number> | undefined) ?? {})) }
    const active = list.filter(l => l.owner_session === me && (l.status === 'running' || l.status === 'retry_wait')).length
    $.ui.status(active > 0 ? `muse: ${active} running` : undefined)

    for (const l of list) {
      if (l.owner_session !== me) continue
      if (l.status === 'orphaned') {
        if (l.orphan_announced) continue
        const a = await lane($, ['ack', l.id, '--orphan'])
        if (a.code !== 0) continue
        await $.prompt.submit({ text: `Muse lane ${l.label ?? l.id} (${l.id}) is orphaned: the supervisor died; \`lane_resume\` continues from the recorded step. Still watching for its terminal state.` })
        continue
      }
      if (!TERMINAL.has(l.status)) continue
      if (l.announced) continue
      let text: string
      const s = await lane($, ['summary', l.id])
      if (s.ok) {
        text = s.out
      } else {
        const n = (tries[l.id] ?? 0) + 1
        if (n < SUMMARY_TRIES) {
          tries[l.id] = n
          await $.state.set({ plugin: 'muse', key: 'summaryTries' }, tries)
          continue
        }
        const st = await lane($, ['status', l.id])
        text = st.out
      }
      const a = await lane($, ['ack', l.id])
      if (a.code !== 0) {
        if (a.code === 3 && l.id in tries) {
          delete tries[l.id]
          await $.state.set({ plugin: 'muse', key: 'summaryTries' }, tries)
        }
        continue
      }
      $.ui.toast(`Muse lane ${l.label ?? l.id} ended: ${l.status}`)
      await $.prompt.submit({ text: `Muse lane ${l.label ?? l.id} (${l.id}) ended: ${l.status}.\n\n${text}` })
      if (l.id in tries) {
        delete tries[l.id]
        await $.state.set({ plugin: 'muse', key: 'summaryTries' }, tries)
      }
    }
  } finally {
    pollInFlight = false
  }
}

export const register: Register = (on, options) => {
  const envFile = String((options as { envFile?: string }).envFile ?? '')

  on('session.start', async ($, e, next) => {
    for (const t of TOOLS) await $.tool.register(t)
    await $.command.register({ name: 'muse', description: 'Show Muse lanes in a pane' })
    $.clock.every(POLL_MS, () => void poll($))
    void poll($)
    return next(e)
  })

  on('command.run', { command: 'muse' }, async $ => {
    await $.ui.open({ id: PANE, title: 'Muse lanes' })
    return { text: 'Muse lanes pane opened.' }
  })

  on('tool.call', { tool: 'mcp__muse__lane_start' }, async ($, e: any) => {
    const stamp = new Date().toISOString().replace(/[-:.]/g, '').slice(0, 15)
    const rand = Math.random().toString(36).slice(2, 8)
    const rootR = await lane($, ['root'])
    let briefsDir: string
    if (rootR.ok && rootR.out) {
      briefsDir = `${rootR.out.split('\n').pop()!.trim()}/_briefs`
    } else {
      const root = (await $.env.get('MUSE_LANES_ROOT')) || `${await $.env.get('HOME')}/.muse-lanes`
      briefsDir = `${root}/_briefs`
    }
    let owner: string
    try {
      owner = await $.session.id()
    } catch {
      return { result: 'Cannot start a lane: session id unavailable.', isError: true }
    }
    if (!owner) return { result: 'Cannot start a lane: session id unavailable.', isError: true }
    const args = ['start', '--cwd', e.cwd, '--effort', e.effort ?? 'max', '--owner-session', owner]
    for (const [i, s] of (e.steps ?? []).entries()) {
      if (s.brief) { args.push('--brief', s.brief); continue }
      if (!s.prompt) return { result: `Step ${i + 1} has neither brief nor prompt.`, isError: true }
      const path = `${briefsDir}/${stamp}-${i + 1}-${rand}.md`
      await $.fs.write(path, s.prompt)
      args.push('--brief', path)
    }
    if (e.label) args.push('--label', e.label)
    if (e.accept) args.push('--accept', e.accept)
    if (e.stall_min) args.push('--stall-min', String(e.stall_min))
    if (envFile && (await $.fs.exists(envFile))) args.push('--env-file', envFile)
    const r = await lane($, args)
    if (!r.ok) return { result: r.out, isError: true }
    const id = r.out.split('\n').pop()!.trim()
    void poll($)
    return { result: `Started lane ${id}. You will get one prompt with its summary when it ends; no need to poll.` }
  })

  on('tool.call', { tool: 'mcp__muse__lane_status' }, async ($, e: any) => answer($, e.id ? ['status', e.id] : ['status']))
  on('tool.call', { tool: 'mcp__muse__lane_summary' }, async ($, e: any) => answer($, ['summary', e.id]))
  on('tool.call', { tool: 'mcp__muse__lane_stop' }, async ($, e: any) => answer($, ['stop', e.id]))
  on('tool.call', { tool: 'mcp__muse__lane_resume' }, async ($, e: any) => answer($, ['resume', e.id]))

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Button, Text } = $.ui.resolve(e)
    const list = ((await read($, lanes)) as Lane[] | undefined) ?? []
    const now = Date.now() / 1000
    const idle = (t?: number | string) => {
      const s = typeof t === 'number' ? t : t ? Date.parse(t) / 1000 : NaN
      return Number.isFinite(s) ? `${Math.round((now - s) / 60)}m idle` : ''
    }
    return (
      <Box flexDirection="column">
        {list.length === 0 && <Text dimColor>No Muse lanes.</Text>}
        {list.slice(0, 30).map(l => (
          <Box key={l.id} flexDirection="row" gap={1}>
            <Text bold={!TERMINAL.has(l.status)} dimColor={TERMINAL.has(l.status)}>
              {l.status.padEnd(10)} {l.label ?? l.id}  step {l.step ?? '-'}/{l.steps ?? '-'}  try {l.attempt ?? '-'}  {l.commits ?? 0} commits  {TERMINAL.has(l.status) ? (l.reason ?? '') : idle(l.last_activity_at)}
            </Text>
            {!TERMINAL.has(l.status) && l.status !== 'orphaned' && (
              <Button key={`stop-${l.id}`} plain onPress={() => void lane($, ['stop', l.id]).then(() => poll($))}>stop</Button>
            )}
            {l.status === 'orphaned' && (
              <Button key={`resume-${l.id}`} plain onPress={() => void lane($, ['resume', l.id]).then(() => poll($))}>resume</Button>
            )}
          </Box>
        ))}
      </Box>
    )
  })
}
