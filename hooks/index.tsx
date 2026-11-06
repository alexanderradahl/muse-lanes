// Muse lanes: tools to start/inspect/stop supervised `muse exec` runs, a pane listing them, and wake-ups when a lane needs the lead.
// Refuses to supervise anything itself: bin/muse-lane owns retries, stalls, acceptance, box tickets and needs-lead facts, and survives this session.
// Wake-ups are exactly-once across sessions: the runner records owner_session per lane, and `ack` claims each announcement.
// An event enters the outbox ($.state, so a reload keeps it) before the runner's ack claims it, and leaves it
// when one prompt carries it: a single event verbatim, several as a digest. The submit is never awaited (it
// resolves only when the turn starts); a dropped one goes back to the outbox, retried after a growing pause.
// Routine progress never wakes.
import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { MuseBox as BoxRow, MuseLane as Lane, MuseWake as Wake } from '../types'

const PANE = 'muse-lanes'
const TITLE = 'Muse lanes'
const lanes = atom({ plugin: 'muse', key: 'lanes' } as const, [] as Lane[])
const boxesRef = atom({ plugin: 'muse', key: 'boxes' } as const, [] as BoxRow[])
const expandedRef = atom({ plugin: 'muse', key: 'expanded' } as const, {} as Record<string, boolean>)
const detailsRef = atom({ plugin: 'muse', key: 'details' } as const, {} as Record<string, string>)
const outboxRef = atom({ plugin: 'muse', key: 'outbox' } as const, [] as Wake[])
const triesRef = atom({ plugin: 'muse', key: 'summaryTries' } as const, {} as Record<string, number>)
const TERMINAL = new Set(['done', 'failed', 'gave_up', 'stopped', 'review_failed'])
const WORK = new Set(['running', 'retry_wait', 'accepting'])
const LIVE = new Set(['queued', ...WORK])
const POLL_MS = 20_000
const SUMMARY_TRIES = 3
const DETAIL_LINES = 40
let pollInFlight = false
let submitting = false
let drops = 0
let retryAt = 0

const TOOLS = [
  {
    name: 'lane_start',
    description:
      'Start a supervised Muse lane: one or more steps run in sequence by `muse exec` (reasoning max by default) in `cwd`, ' +
      'retried with backoff for transient failures (stalls, timeouts, 429/5xx, network errors), once more for model failed/cancelled, ' +
      'never for auth or spawn failures, then the optional `accept` shell command. Use one step for an agent, ' +
      'several for a workflow. Returns the lane id at once. The session is woken only when the lane ends or needs the lead ' +
      '(a question the lane escalated, a box wait past budget, a scope violation, a failed accept or review), so do not poll.',
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
        accept: { type: 'string', description: 'Acceptance shell command run in cwd after the last step. It may print `LANE-PHASE: <name>` and `LANE-NEEDS-LEAD: <kind> <detail>` lines.' },
        label: { type: 'string' },
        effort: { type: 'string', description: 'Reasoning effort, default max.' },
        stall_min: { type: 'number', description: 'Minutes of no log and no git change before a retry, default 40.' },
        review: {
          description: 'Muse pre-review after a passing accept (a pre-filter; the Opus lead still does the final review): true, or {brief, rounds} with rounds = max fix re-runs after a FAIL (default 1, 0 reviews once with no fix).',
          anyOf: [{ type: 'boolean' }, { type: 'object', properties: { brief: { type: 'string' }, rounds: { type: 'number' } } }],
        },
        consult_max: { type: 'number', description: 'Max mid-step consult answers per step, default 3.' },
        scope: { type: 'array', items: { type: 'string' }, description: 'Path globs the lane may change; a change outside them ends the lane with a scope_violation for the lead.' },
        box: { type: 'string', description: 'A gate box handed to this lane. Accepts on one box run one at a time in queue order; the accept sees LANE_BOX.' },
        advisor: {
          type: 'object',
          description: 'Read-only Claude advisor for mid-step questions: {model: "sonnet" (default) | "opus", max: calls per lane (default 3)}. It cannot change acceptance or scope; it escalates those to the lead.',
          properties: { model: { type: 'string', enum: ['sonnet', 'opus'] }, max: { type: 'number' } },
        },
      },
    },
  },
  { name: 'lane_status', description: 'Muse lanes and their state (active view, or one by id).', inputSchema: { type: 'object', properties: { id: { type: 'string' }, all: { type: 'boolean', description: 'List every lane, not just the active view.' } } } },
  { name: 'lane_summary', description: "A lane's summary: attempts, commits, acceptance, consults, pre-review, each step's final answer, and the ready-to-merge evidence.", inputSchema: { type: 'object', required: ['id'], properties: { id: { type: 'string' } } } },
  { name: 'lane_stop', description: 'Stop a running Muse lane.', inputSchema: { type: 'object', required: ['id'], properties: { id: { type: 'string' } } } },
  { name: 'lane_resume', description: 'Resume an orphaned lane (its supervisor died) from its recorded step.', inputSchema: { type: 'object', required: ['id'], properties: { id: { type: 'string' } } } },
  {
    name: 'lane_answer',
    description: "The lead's reply to a lane that needs it: `text` answers an escalated question (the lane reads it as .lane/ANSWER.md); `box` moves a lane waiting on a busy box to another box.",
    inputSchema: { type: 'object', required: ['id'], properties: { id: { type: 'string' }, text: { type: 'string' }, box: { type: 'string' } } },
  },
  { name: 'lane_boxes', description: 'Gate boxes: which lane holds each, the lanes queued for it, and the lease file holder.', inputSchema: { type: 'object', properties: {} } },
]

async function lane($: any, args: string[], timeoutMs = 60_000) {
  const r = await $.process.run(['python3', `${$.plugin.root}/bin/muse-lane`, ...args], { timeoutMs })
  return { ok: r.exitCode === 0, code: r.exitCode as number, out: (r.stdout + (r.exitCode === 0 ? '' : `\n${r.stderr}`)).trim() }
}

// Polls without awaiting; a poll cut short (a reload, a test ending) is dropped, the next one catches up.
const kick = ($: any): void => {
  void poll($).catch(() => undefined)
}

async function answer($: any, args: string[]) {
  const r = await lane($, args, 30_000)
  kick($)
  return r.ok ? { result: r.out || "ok" } : { result: r.out, isError: true as const }
}

async function sessionId($: any): Promise<string> {
  try {
    return (await $.session.id()) || ''
  } catch {
    return ''
  }
}

const name = (l: Lane) => l.label || l.id
const isWorking = (l: Lane) => WORK.has(l.status)
const isLive = (l: Lane) => LIVE.has(l.status)
// A lane wants the lead while it is live with an open needs-lead fact, or after it ended any way but done.
const wantsLead = (l: Lane) =>
  (!TERMINAL.has(l.status) && !!l.needs_lead) || l.status === 'orphaned' || (TERMINAL.has(l.status) && l.status !== 'done' && l.status !== 'stopped')

function needsLeadText(l: Lane): string {
  const n = l.needs_lead!
  const how =
    n.kind === 'question'
      ? `Reply with lane_answer {id: "${l.id}", text}; the lane keeps working meanwhile.`
      : n.kind === 'box_wait_timeout'
        ? `Move it with lane_answer {id: "${l.id}", box}, or lane_stop it. It keeps its place in the queue.`
        : `See lane_summary ${l.id}.`
  return `Muse lane ${name(l)} (${l.id}) needs the lead: ${n.kind}: ${n.detail}\n${how}`
}

function evidenceLines(l: Lane): string[] {
  const ev = l.evidence
  if (!ev) return []
  const out = [`READY TO MERGE: ${ev.branch} @ ${ev.head.slice(0, 10)}, ${ev.commits} commits since ${ev.head_start.slice(0, 10)}`, `accept log: ${ev.accept_log}`]
  if (ev.review_files.length > 0) out.push(`pre-review: ${ev.review_files.join(', ')}`)
  out.push(`summary: ${ev.summary_path}`)
  return out
}

function digestBlock(l: Lane, kind: Wake['kind']): string {
  const head = `- ${name(l)} (${l.id}): ${kind === 'lead' ? 'needs the lead' : l.status}`
  const lines = [head]
  if (kind === 'lead' || (kind === 'end' && l.needs_lead)) lines.push(`  ${l.needs_lead!.kind}: ${l.needs_lead!.detail}`)
  if (kind === 'orphan') lines.push('  supervisor died; lane_resume continues from the recorded step')
  if (kind === 'end' && l.status === 'done') for (const e of evidenceLines(l)) lines.push(`  ${e}`)
  if (kind === 'end' && l.status !== 'done' && !l.needs_lead && l.reason) lines.push(`  ${l.reason}`)
  return lines.join('\n')
}

function wake(l: Lane, kind: Wake['kind'], full: string): Wake {
  const seq = kind === 'lead' ? l.needs_lead!.seq : 0
  return { key: `${l.id}:${kind}:${seq}`, id: l.id, kind, full, block: digestBlock(l, kind), loud: kind !== 'end' || (l.status !== 'done' && l.status !== 'stopped') }
}

// Hands the outbox to one prompt unless one is already on its way. Entries leave the outbox as the prompt is
// queued, so a reload while it waits for its turn never sends them twice. A drop (an interrupt, a hook's refusal)
// puts them back, retried no sooner than 20 s, doubling to 10 min while drops repeat.
async function flush($: any) {
  if (submitting) return
  if (retryAt && (await $.clock.now()) < retryAt) return
  let box: Wake[] = []
  await update($, outboxRef, o => {
    box = o
    return []
  })
  if (box.length === 0) return
  submitting = true
  const text =
    box.length === 1
      ? box[0]!.full
      : [`Muse: ${box.length} lane events.`, ...box.map(w => w.block), 'Full text: lane_summary <id>.'].join('\n\n')
  const putBack = async () => {
    drops += 1
    retryAt = (await $.clock.now()) + Math.min(20_000 * 2 ** (drops - 1), 600_000)
    await update($, outboxRef, o => [...box.filter(w => !o.some(x => x.key === w.key)), ...o])
  }
  void Promise.resolve()
    .then(() => $.prompt.submit({ text }))
    .then(async (r: any) => {
      if (r && r.drop) return putBack()
      drops = 0
      retryAt = 0
    }, putBack)
    .catch(() => undefined)
    .finally(() => { submitting = false })
}

// Queues an event, then claims it with the runner's ack. A reload between the two leaves it queued and unclaimed,
// so the next poll claims it again under the same key; an ack someone else won takes it back out.
async function claim($: any, w: Wake, ackArgs: string[]): Promise<number> {
  await update($, outboxRef, o => (o.some(x => x.key === w.key) ? o : [...o, w]))
  const a = await lane($, ackArgs)
  if (a.code !== 0) await update($, outboxRef, o => o.filter(x => x.key !== w.key))
  return a.code
}

async function poll($: any) {
  if (pollInFlight) return
  pollInFlight = true
  try {
    const r = await lane($, ['status', '--json', '--active'])
    if (!r.ok) return
    let list: Lane[] = []
    try { list = JSON.parse(r.out) } catch { return }
    await $.state.set({ plugin: 'muse', key: 'lanes' }, list)

    // Boxes cost one more runner call: only while a live lane has one.
    let boxes: BoxRow[] = []
    if (list.some(l => l.box && !TERMINAL.has(l.status))) {
      const b = await lane($, ['boxes', '--json'])
      if (b.ok) {
        try { boxes = JSON.parse(b.out) } catch { boxes = [] }
      }
    }
    await $.state.set({ plugin: 'muse', key: 'boxes' }, boxes)

    const me = await sessionId($)
    if (!me) return
    const mine = list.filter(l => l.owner_session === me)
    const working = mine.filter(isWorking)
    const waiting = mine.filter(l => !TERMINAL.has(l.status) && (l.needs_lead || l.status === 'orphaned')).length
    if (working.length === 1 && waiting === 0) {
      const l = working[0]!
      $.ui.status(`muse: ${name(l)} ${l.phase || l.status}`)
    } else if (working.length > 0 || waiting > 0) {
      $.ui.status(`muse: ${working.length} running${waiting ? ` · ${waiting} need lead` : ''}`)
    } else {
      $.ui.status(undefined)
    }

    const tries = { ...((((await read($, triesRef)) as Record<string, number> | undefined) ?? {})) }
    let triesDirty = false
    const wakes: Wake[] = []
    for (const l of mine) {
      if (l.status === 'orphaned') {
        if (l.orphan_announced) continue
        const w = wake(l, 'orphan', `Muse lane ${name(l)} (${l.id}) is orphaned: the supervisor died; \`lane_resume\` continues from the recorded step. Still watching for its terminal state.`)
        if ((await claim($, w, ['ack', l.id, '--orphan'])) === 0) wakes.push(w)
        continue
      }
      if (!TERMINAL.has(l.status)) {
        if (!l.needs_lead || l.needs_lead_announced) continue
        const w = wake(l, 'lead', needsLeadText(l))
        if ((await claim($, w, ['ack', l.id, '--lead', String(l.needs_lead.seq)])) === 0) wakes.push(w)
        continue
      }
      if (l.announced) continue
      let text: string
      const s = await lane($, ['summary', l.id])
      if (s.ok) {
        text = s.out
      } else {
        const n = (tries[l.id] ?? 0) + 1
        if (n < SUMMARY_TRIES) {
          tries[l.id] = n
          triesDirty = true
          continue
        }
        text = (await lane($, ['status', l.id])).out
      }
      const w = wake(l, 'end', `Muse lane ${name(l)} (${l.id}) ended: ${l.status}.\n\n${text}`)
      const code = await claim($, w, ['ack', l.id])
      if (code !== 0) {
        if (code === 3 && l.id in tries) {
          delete tries[l.id]
          triesDirty = true
        }
        continue
      }
      if (l.id in tries) {
        delete tries[l.id]
        triesDirty = true
      }
      wakes.push(w)
    }
    if (triesDirty) await $.state.set({ plugin: 'muse', key: 'summaryTries' }, tries)
    if (wakes.length > 0) {
      const loud = wakes.filter(w => w.loud)
      const what = (w: Wake) => {
        const l = list.find(x => x.id === w.id)!
        return `Muse lane ${name(l)}: ${w.kind === 'lead' ? `needs the lead (${l.needs_lead!.kind})` : l.status}`
      }
      // Toasts and notifications only for what needs the lead; a done lane wakes quietly.
      const alert = loud.length === 1 ? what(loud[0]!) : loud.length > 1 ? `Muse: ${loud.length} lanes need the lead` : ''
      if (alert) {
        $.ui.toast(alert, { timeoutMs: 15_000 })
        void Promise.resolve($.ui.notify(alert, { title: 'Muse lanes' })).catch(() => undefined)
      }
    }
    await flush($)
  } finally {
    pollInFlight = false
  }
}

async function openPane($: any) {
  return $.ui.open({ id: PANE, title: TITLE })
}

// Fetches what a drill-down shows: the summary once a lane ended, its status block while live.
async function loadDetail($: any, l: Lane) {
  const r = await lane($, TERMINAL.has(l.status) ? ['summary', l.id] : ['status', l.id])
  const text = r.out.split('\n').slice(0, DETAIL_LINES).join('\n') || '(nothing yet)'
  await update($, detailsRef, d => ({ ...d, [l.id]: text }))
}

export const register: Register = (on, options) => {
  const envFile = String((options as { envFile?: string }).envFile ?? '')

  on('session.start', async ($, e, next) => {
    for (const t of TOOLS) await $.tool.register(t)
    await $.command.register({ name: 'muse', description: 'Show Muse lanes in a pane' })
    $.clock.every(POLL_MS, () => kick($))
    kick($)
    return next(e)
  })

  on('command.run', { command: 'muse' }, async $ => {
    await openPane($)
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
    const owner = await sessionId($)
    if (!owner) return { result: 'Cannot start a lane: session id unavailable.', isError: true as const }
    const args = ['start', '--cwd', e.cwd, '--effort', e.effort ?? 'max', '--owner-session', owner]
    for (const [i, s] of (e.steps ?? []).entries()) {
      if (s.brief) { args.push('--brief', s.brief); continue }
      if (!s.prompt) return { result: `Step ${i + 1} has neither brief nor prompt.`, isError: true as const }
      const path = `${briefsDir}/${stamp}-${i + 1}-${rand}.md`
      await $.fs.write(path, s.prompt)
      args.push('--brief', path)
    }
    if (e.label) args.push('--label', e.label)
    if (e.accept) args.push(`--accept=${e.accept}`)
    if (e.stall_min) args.push('--stall-min', String(e.stall_min))
    if (e.review === true) {
      args.push('--review')
    } else if (e.review && typeof e.review === 'object') {
      args.push('--review')
      if ((e.review as { brief?: unknown }).brief) args.push('--review-brief', String((e.review as { brief?: unknown }).brief))
      const rr = (e.review as { rounds?: unknown }).rounds
      if (rr !== undefined && rr !== null) args.push('--review-rounds', String(rr))
    }
    if (e.consult_max !== undefined && e.consult_max !== null) args.push('--consult-max', String(e.consult_max))
    for (const g of Array.isArray(e.scope) ? e.scope : []) args.push('--scope', String(g))
    if (e.box) args.push('--box', String(e.box))
    if (e.advisor && typeof e.advisor === 'object') {
      args.push('--advisor-model', String(e.advisor.model ?? 'sonnet'))
      if (e.advisor.max !== undefined && e.advisor.max !== null) args.push('--advisor-max', String(e.advisor.max))
    }
    if (envFile && (await $.fs.exists(envFile))) args.push('--env-file', envFile)
    const r = await lane($, args)
    if (!r.ok) return { result: r.out, isError: true as const }
    const id = r.out.split('\n').pop()!.trim()
    let shown = false
    try { shown = !!(await openPane($))?.isPlaced } catch { shown = false }
    kick($)
    return { result: `Started lane ${id}. You will be woken when it ends or needs you; no need to poll.${shown ? '' : ' /muse shows the lanes pane.'}` }
  })

  on('tool.call', { tool: 'mcp__muse__lane_status' }, async ($, e: any) => answer($, e.id ? ['status', e.id] : (e.all ? ['status'] : ['status', '--active'])))
  on('tool.call', { tool: 'mcp__muse__lane_summary' }, async ($, e: any) => answer($, ['summary', e.id]))
  on('tool.call', { tool: 'mcp__muse__lane_stop' }, async ($, e: any) => answer($, ['stop', e.id]))
  on('tool.call', { tool: 'mcp__muse__lane_resume' }, async ($, e: any) => answer($, ['resume', e.id]))
  on('tool.call', { tool: 'mcp__muse__lane_boxes' }, async $ => answer($, ['boxes']))
  on('tool.call', { tool: 'mcp__muse__lane_answer' }, async ($, e: any) => {
    if (!e.text && !e.box) return { result: 'lane_answer needs text, box, or both.', isError: true as const }
    const args = ['answer', e.id]
    if (e.text) args.push(`--text=${String(e.text)}`)
    if (e.box) args.push('--box', String(e.box))
    return answer($, args)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Button, Text } = $.ui.resolve(e)
    const list = ((await read($, lanes)) as Lane[] | undefined) ?? []
    const boxes = ((await read($, boxesRef)) as BoxRow[] | undefined) ?? []
    const expanded = ((await read($, expandedRef)) as Record<string, boolean> | undefined) ?? {}
    const details = ((await read($, detailsRef)) as Record<string, string> | undefined) ?? {}
    const me = await sessionId($)
    const now = Date.now() / 1000
    const ts = (t?: number | string | null) => {
      if (t === undefined || t === null) return NaN
      const s = typeof t === 'number' ? t : Date.parse(t) / 1000
      return Number.isFinite(s) ? s : NaN
    }
    const dur = (sec: number) => {
      if (!Number.isFinite(sec) || sec < 0) return ''
      if (sec < 120) return `${Math.round(sec)}s`
      if (sec < 3600) return `${Math.round(sec / 60)}m`
      return `${Math.floor(sec / 3600)}h ${Math.round((sec % 3600) / 60)}m`
    }
    // Flagged until the lead has been woken for it; an ended lane drops to the bottom once announced.
    const isHot = (l: Lane) => wantsLead(l) && !(TERMINAL.has(l.status) && l.announced)
    const rank = (l: Lane) => (isHot(l) ? 0 : isLive(l) ? (l.owner_session === me ? 1 : 2) : l.status === 'done' ? 3 : 4)
    const ordered = [...list].sort((a, b) => rank(a) - rank(b))
    const running = list.filter(isLive).length
    const need = list.filter(isHot).length
    const ready = list.filter(l => l.status === 'done' && l.evidence).length

    const review = (l: Lane) => {
      const rounds = l.review_rounds ?? []
      if (l.review_error) return 'review error'
      if (rounds.length === 0) return ''
      const last = rounds[rounds.length - 1]!
      return `review ${last.verdict ?? '?'} r${last.round ?? rounds.length}`
    }
    // Row: the toggle names the lane (the Desktop app draws only a Button's label), then where it is now.
    const now1 = (l: Lane) => {
      const done = TERMINAL.has(l.status)
      const bits = [l.status]
      if (l.phase) {
        const el = dur((done ? ts(l.updated_at) : now) - ts(l.phase_started))
        bits.push(`${l.phase}${el ? ` ${el}` : ''}`)
      }
      if (!done) {
        const idleSec = now - ts(l.last_activity_at)
        if (Number.isFinite(idleSec) && idleSec >= 60) {
          const nearStall = l.stall_sec ? idleSec > 0.75 * l.stall_sec : false
          bits.push(`idle ${Math.round(idleSec / 60)}m${nearStall ? ' (near stall)' : ''}`)
        }
      }
      return bits.join(' · ')
    }
    // Second line: box, total time, pre-review, commits.
    const line2 = (l: Lane) => {
      const bits: string[] = []
      if (l.box) bits.push(`box ${l.box}${l.box_state === 'queued' ? ' (queued)' : ''}`)
      const total = dur((TERMINAL.has(l.status) ? ts(l.updated_at) : now) - ts(l.started_at))
      if (total) bits.push(`total ${total}`)
      const rv = review(l)
      if (rv) bits.push(rv)
      let c = `${l.commits ?? 0} commits`
      if ((l.commits ?? 0) > 0 && l.last_subject) c += `: ${l.last_subject}`
      if (l.branch) c += ` (${l.branch})`
      bits.push(c)
      return bits.join(' · ')
    }
    const alert = (l: Lane): string | null => {
      if (l.needs_lead && l.status !== 'done') return `needs lead: ${l.needs_lead.kind}: ${l.needs_lead.detail}`
      if (l.status === 'orphaned') return 'supervisor died: resume continues from the recorded step'
      if ((l.status === 'failed' || l.status === 'review_failed') && l.accept_tail) {
        const tail = l.accept_tail.split('\n').filter(s => s.trim()).slice(-3).map(s => (s.length > 120 ? s.slice(0, 117) + '...' : s))
        if (tail.length > 0) return `accept: ${tail.join(' | ')}`
      }
      if (TERMINAL.has(l.status) && l.reason && l.status !== 'done') return l.reason
      return null
    }
    const toggle = (l: Lane) => {
      let opened = false
      void update($, expandedRef, x => {
        opened = !x[l.id]
        return { ...x, [l.id]: opened }
      }).then(() => (opened ? loadDetail($, l) : undefined)).catch(() => undefined)
    }
    const act = (args: string[]) => void lane($, args).then(() => kick($)).catch(() => undefined)

    return (
      <Box flexDirection="column">
        <Text bold>
          {running} running · {need} need lead · {ready} ready
        </Text>
        {boxes.length > 0 && (
          <Box flexDirection="column" marginTop={1}>
            <Text dimColor>Boxes</Text>
            {boxes.map(b => {
              const holder = b.holder_lane ? (list.find(l => l.id === b.holder_lane)?.label || b.holder_lane) : 'free'
              const queue = b.queue.filter(id => id !== b.holder_lane).map(id => list.find(l => l.id === id)?.label || id)
              const lease = b.lease ? ` · lease ${b.lease.who}: ${b.lease.what}` : ''
              return (
                <Text key={`box-${b.box}`}>
                  {b.box}: {holder}{queue.length ? ` · queue ${queue.join(', ')}` : ''}{lease}
                </Text>
              )
            })}
          </Box>
        )}
        <Box flexDirection="column" marginTop={1}>
          {ordered.length === 0 && <Text dimColor>No Muse lanes.</Text>}
          {ordered.slice(0, 30).map(l => {
            const done = TERMINAL.has(l.status)
            const hot = isHot(l)
            const warn = alert(l)
            const open = !!expanded[l.id]
            return (
              <Box key={l.id} flexDirection="column" marginBottom={open ? 1 : 0}>
                <Box flexDirection="row" gap={1}>
                  <Button key={`row-${l.id}`} plain label={`${open ? '▾' : '▸'} ${hot ? '! ' : ''}${name(l)}`} onPress={() => toggle(l)} />
                  <Text bold={!done} dimColor={done && !hot} color={hot ? 'warning' : undefined}>
                    {now1(l)}
                  </Text>
                </Box>
                <Box flexDirection="column" marginLeft={2}>
                  <Text dimColor>{line2(l)}</Text>
                  {warn && <Text color="warning">{warn}</Text>}
                </Box>
                {open && (
                  <Box flexDirection="column" marginLeft={2}>
                    {evidenceLines(l).map((s, i) => <Text key={`ev-${l.id}-${i}`} color="success">{s}</Text>)}
                    <Text dimColor>{details[l.id] ?? 'loading...'}</Text>
                    <Box flexDirection="row" gap={1}>
                      {!done && l.status !== 'orphaned' && <Button key={`stop-${l.id}`} label="stop" onPress={() => act(['stop', l.id])} />}
                      {l.status === 'orphaned' && <Button key={`resume-${l.id}`} label="resume" onPress={() => act(['resume', l.id])} />}
                      <Button key={`refresh-${l.id}`} label="refresh" onPress={() => void loadDetail($, l).catch(() => undefined)} />
                    </Box>
                  </Box>
                )}
              </Box>
            )
          })}
        </Box>
      </Box>
    )
  })
}
