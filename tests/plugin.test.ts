// Plugin tests for muse. The runner (bin/muse-lane) is faked beneath the
// plugin: `process.run` is answered the way the runner answers `status
// --json`, `summary` and `ack` (plus the `status`, `root`, `start` and
// `resume` calls the plugin makes), with ack's claim semantics (exit 3 when
// the marker already exists).
//
// The kit ships no real state, so an in-memory store answers `state.get` and
// `state.set`. Every test reads `muse/lanes` back out of that store, which
// pins the host's `$.state.set(ref, value)` shape: a write that lands
// anywhere else, or with no value, fails the read-back.
import { test, expect, mock } from 'claude-code/testing'
import type { Engine, MockClock } from 'claude-code/testing'
import type { On } from 'claude-code'

const ME = 'sess-test-me'
const OTHER = 'sess-other'
const TERMINAL = new Set(['done', 'failed', 'gave_up', 'stopped', 'review_failed'])
const NON_TERMINAL = new Set(['queued', 'running', 'retry_wait', 'accepting'])

type FakeLane = {
  id: string
  label?: string
  status: string
  owner: string | null
  announced: boolean
  orphanAnnounced: boolean
  summary?: string
  phase?: string
  updatedAt?: string
  needsLead?: { seq: number; kind: string; detail: string } | null
  leadAcked?: number[]
  box?: string | null
  evidence?: Record<string, unknown> | null
}

type World = {
  lanes: FakeLane[]
  submits: string[]
  statuses: Array<string | undefined>
  toasts: string[]
  runs: string[]
  statusJsonCalls: number
  summaryCalls: string[]
  ackCalls: string[]
  writes: Array<{ path: string; text: string }>
  startArgs: string[][]
  store: Map<string, unknown>
  sets: Array<{ plugin: unknown; key: unknown; value: unknown }>
  gate: Promise<void> | null
  notifies: string[]
  opens: number
  placed: boolean
  dropNext: number
  boxes: unknown[]
  outboxAtAck: string[]
}

// One row the way `muse-lane status --json` serves it. Stamps a fresh
// updated_at on first serve so the active filter treats test lanes as recent
// while staying deterministic across calls.
function rowJson(l: FakeLane) {
  if (!l.updatedAt) l.updatedAt = new Date().toISOString()
  return {
    id: l.id,
    label: l.label ?? '',
    cwd: '/tmp/work',
    status: l.status,
    step: 1,
    steps: 1,
    attempt: 1,
    commits: 0,
    last_activity_at: '2026-10-01T00:00:00+00:00',
    reason: null,
    owner_session: l.owner,
    announced: l.announced,
    orphan_announced: l.orphanAnnounced,
    phase: l.phase ?? 'step:1',
    phase_started: l.updatedAt,
    started_at: l.updatedAt,
    updated_at: l.updatedAt,
    stall_sec: 2400,
    last_subject: null,
    accept_tail: '',
    review_rounds: [],
    review_error: null,
    needs_lead: l.needsLead ? { ...l.needsLead, at: '2026-11-06T00:00:00Z' } : null,
    needs_lead_announced: !!l.needsLead && (l.leadAcked ?? []).includes(l.needsLead.seq),
    box: l.box ?? null,
    box_state: null,
    box_queued_at: null,
    branch: null,
    head: null,
    evidence: l.evidence ?? null,
    advisor_calls: 0,
  }
}

function isActive(l: FakeLane): boolean {
  if (l.status === 'orphaned' || NON_TERMINAL.has(l.status)) return true
  if (!TERMINAL.has(l.status)) return true
  if (!l.updatedAt) l.updatedAt = new Date().toISOString()
  const u = Date.parse(l.updatedAt)
  if (!Number.isFinite(u)) return true
  return Date.now() - u <= 24 * 3600 * 1000
}

function setup(on: On): { world: World; clock: MockClock } {
  const clock = mock.clock(on)
  mock.env(on, { HOME: '/tmp/fake-home' })
  const world: World = {
    lanes: [],
    submits: [],
    statuses: [],
    toasts: [],
    runs: [],
    statusJsonCalls: 0,
    summaryCalls: [],
    ackCalls: [],
    writes: [],
    startArgs: [],
    store: new Map(),
    sets: [],
    gate: null,
    notifies: [],
    opens: 0,
    placed: true,
    dropNext: 0,
    boxes: [],
    outboxAtAck: [],
  }

  const runOk = (stdout: string) => ({
    value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
  })
  const runFail = (code: number, stderr: string) => ({
    value: { exitCode: code, stdout: '', stderr, isStdoutTruncated: false, isStderrTruncated: false },
  })

  on('process.run', async (_h, e) => {
    const rest = e.argv.slice(2)
    world.runs.push(rest.join(' '))
    const cmd = rest[0] ?? ''
    const a = rest[1]
    const b = rest[2]
    if (cmd === 'status' && rest.includes('--json')) {
      world.statusJsonCalls += 1
      if (world.gate) await world.gate
      let lanes = [...world.lanes]
      if (rest.includes('--active')) lanes = lanes.filter(isActive)
      const li = rest.indexOf('--limit')
      if (li >= 0) lanes = lanes.slice(0, Math.max(0, Number(rest[li + 1] ?? 0)))
      return runOk(JSON.stringify(lanes.map(rowJson)))
    }
    if (cmd === 'status' && a === '--active') {
      const active = world.lanes.filter(isActive)
      const lines = active.map(l => `${l.id}  ${l.status}  step 1/1 att 1  updated now`)
      if (world.lanes.length > active.length) {
        lines.push(`(+${world.lanes.length - active.length} older lanes not shown)`)
      }
      if (lines.length === 0) return runOk('(no lanes)')
      return runOk(lines.join('\n'))
    }
    if (cmd === 'status' && a === undefined) {
      if (world.lanes.length === 0) return runOk('(no lanes)')
      return runOk(world.lanes.map(l => `${l.id}  ${l.status}  step 1/1 att 1  updated now`).join('\n'))
    }
    if (cmd === 'status') {
      const l = world.lanes.find(l => l.id === a)
      if (!l) return runFail(1, `muse-lane: unknown lane: ${a}`)
      return runOk(`id: ${l.id}\nlabel: ${l.label ?? ''}\nstatus: ${l.status}\n`)
    }
    if (cmd === 'summary') {
      world.summaryCalls.push(a ?? '')
      const l = world.lanes.find(l => l.id === a)
      if (!l || l.summary === undefined) return runFail(1, `muse-lane: no summary yet for ${a}`)
      return runOk(l.summary)
    }
    if (cmd === 'ack') {
      world.ackCalls.push(rest.join(' '))
      world.outboxAtAck.push(JSON.stringify(world.store.get('muse/outbox') ?? []))
      const l = world.lanes.find(l => l.id === a)
      if (!l) return runFail(1, `muse-lane: unknown lane: ${a}`)
      if (b === '--lead') {
        const seq = Number(rest[3])
        if (TERMINAL.has(l.status)) return runFail(2, `muse-lane: lane is ${l.status}`)
        if (!l.needsLead || l.needsLead.seq !== seq) return runFail(2, 'muse-lane: no such needs-lead seq')
        l.leadAcked = l.leadAcked ?? []
        if (l.leadAcked.includes(seq)) return runFail(3, '')
        l.leadAcked.push(seq)
        return runOk('')
      }
      if (b === '--orphan') {
        if (l.status !== 'orphaned') return runFail(2, `muse-lane: lane is ${l.status}, not orphaned`)
        if (l.orphanAnnounced) return runFail(3, '')
        l.orphanAnnounced = true
        return runOk('')
      }
      if (!TERMINAL.has(l.status)) return runFail(2, `muse-lane: lane is ${l.status}, not terminal`)
      if (l.announced) return runFail(3, '')
      l.announced = true
      return runOk('')
    }
    if (cmd === 'root') return runOk('/tmp/fake-lanes-root')
    if (cmd === 'boxes') return runOk(JSON.stringify(world.boxes))
    if (cmd === 'answer') {
      const l = world.lanes.find(l => l.id === a)
      if (!l) return runFail(1, `muse-lane: unknown lane: ${a}`)
      if (TERMINAL.has(l.status)) return runFail(2, `muse-lane: lane is ${l.status}`)
      return runOk('answered')
    }
    if (cmd === 'start') {
      world.startArgs.push([...rest])
      return runOk(`lane-new-${world.startArgs.length}`)
    }
    if (cmd === 'resume') {
      const l = world.lanes.find(l => l.id === a)
      if (!l) return runFail(1, `muse-lane: unknown lane: ${a}`)
      l.status = 'running'
      return runOk(l.id)
    }
    return runFail(1, `fake runner: unknown command: ${rest.join(' ')}`)
  })

  on('session.id', () => ({ value: ME }))
  on('session.start', (_h, e) => ({ cwd: e.cwd }))
  on('prompt.submit', (_h, e) => {
    if (world.dropNext > 0) {
      world.dropNext -= 1
      return { drop: 'the prompt was removed from the queue before it ran' }
    }
    world.submits.push(e.text)
    return { text: e.text }
  })
  on('ui.open', () => {
    world.opens += 1
    return { value: world.placed ? { isPlaced: true as const } : { isPlaced: false as const, reason: 'narrow' } }
  })
  on('ui.notify', (_h, e) => {
    world.notifies.push(e.text)
    return { value: { isSent: true as const, channel: 'terminal_bell' as const } }
  })
  on('tool.register', (_h, e) => ({ value: { tool: e.name } }))
  on('command.register', (_h, e) => ({ value: { command: e.name } }))
  on('state.get', (_h, e) => {
    const hit = world.store.get(`${e.plugin}/${e.key}`)
    return { value: { value: hit, version: hit === undefined ? 0 : 1 } }
  })
  on('state.set', (_h, e) => {
    world.sets.push({ plugin: e.plugin, key: e.key, value: e.value })
    world.store.set(`${e.plugin}/${e.key}`, e.value)
    return { value: { isSet: true as const, version: 1 } }
  })
  on('fs.write', (_h, e) => {
    world.writes.push({ path: e.path, text: e.text })
    return { value: undefined }
  })
  on('fs.exists', () => ({ value: false }))
  on('ui.status', (_h, e) => {
    world.statuses.push(e.text)
    return { value: undefined }
  })
  on('ui.toast', (_h, e) => {
    world.toasts.push(e.text)
    return { value: undefined }
  })

  return { world, clock }
}

async function begin($: Engine, clock: MockClock): Promise<void> {
  await $.session.start({ cwd: '/tmp', surface: 'terminal', isInteractive: true })
  await clock.settle()
}

// One poll, driven through lane_status the way a session drives it.
async function pollOnce($: Engine, clock: MockClock): Promise<void> {
  await $.tool.call({ tool: 'mcp__muse__lane_status' })
  await clock.settle()
}

async function callMcp(
  $: Engine,
  input: { tool: `mcp__muse__${string}`; [arg: string]: unknown },
): Promise<{ result: string; isError?: boolean }> {
  const r = await $.tool.call(input)
  if ('deny' in r) throw new Error(`tool call denied: ${input.tool}`)
  return r as unknown as { result: string; isError?: boolean }
}

// Every `state.set` the plugin made carried a bare ref and a value, and the
// lane list landed where the pane reads it.
function expectStateShape(world: World): void {
  for (const s of world.sets) {
    expect(s.plugin).toBe('muse')
    expect(typeof s.key).toBe('string')
    expect(s.value).toBeDefined()
  }
  expect(world.store.get('muse/lanes')).toEqual(world.lanes.map(rowJson))
}

test('owned lane reaching done is announced exactly once', async ($, on) => {
  const { world, clock } = setup(on)
  await begin($, clock)

  world.lanes.push({
    id: 'lane-1', label: 'alpha', status: 'running',
    owner: ME, announced: false, orphanAnnounced: false,
    summary: 'alpha summary: all green',
  })
  await pollOnce($, clock)
  expect(world.submits).toHaveLength(0)

  world.lanes[0]!.status = 'done'
  await pollOnce($, clock)
  expect(world.submits).toHaveLength(1)
  expect(world.submits[0]).toContain('alpha summary: all green')
  expect(world.submits[0]).toContain('done')
  expect(world.submits[0]).toContain('lane-1')

  await pollOnce($, clock)
  await pollOnce($, clock)
  expect(world.submits).toHaveLength(1)
  expect(world.ackCalls.filter(c => c === 'ack lane-1')).toHaveLength(1)
  expectStateShape(world)
})

test('lane owned by another session is never submitted', async ($, on) => {
  const { world, clock } = setup(on)
  await begin($, clock)

  world.lanes.push({
    id: 'lane-9', label: 'foreign', status: 'done',
    owner: OTHER, announced: false, orphanAnnounced: false,
    summary: 'foreign summary',
  })
  await pollOnce($, clock)
  await pollOnce($, clock)
  expect(world.submits).toHaveLength(0)
  expect(world.ackCalls).toHaveLength(0)
  expectStateShape(world)
})

test('orphaned lane is announced once, then its real end after resume', async ($, on) => {
  const { world, clock } = setup(on)
  await begin($, clock)

  world.lanes.push({
    id: 'lane-2', label: 'beta', status: 'orphaned',
    owner: ME, announced: false, orphanAnnounced: false,
  })
  await pollOnce($, clock)
  expect(world.submits).toHaveLength(1)
  expect(world.submits[0]).toContain('orphaned')
  expect(world.submits[0]).toContain('lane-2')
  await pollOnce($, clock)
  expect(world.submits).toHaveLength(1)

  const resumed = await callMcp($, { tool: 'mcp__muse__lane_resume', id: 'lane-2' })
  expect(resumed.isError).toBeFalsy()
  expect(resumed.result).toContain('lane-2')
  await clock.settle()
  await pollOnce($, clock)
  expect(world.submits).toHaveLength(1)

  world.lanes[0]!.status = 'failed'
  world.lanes[0]!.summary = 'beta summary: exploded'
  await pollOnce($, clock)
  expect(world.submits).toHaveLength(2)
  expect(world.submits[1]).toContain('beta summary: exploded')
  await pollOnce($, clock)
  expect(world.submits).toHaveLength(2)
  expectStateShape(world)
})

test('a failed lane toasts alongside the wake-up; a done lane wakes quietly', async ($, on) => {
  const { world, clock } = setup(on)
  await begin($, clock)

  world.lanes.push({
    id: 'lane-8', label: 'hotel', status: 'done',
    owner: ME, announced: false, orphanAnnounced: false,
    summary: 'hotel summary',
  })
  await pollOnce($, clock)
  expect(world.submits).toHaveLength(1)
  expect(world.toasts).toHaveLength(0)

  world.lanes.push({
    id: 'lane-18', label: 'india', status: 'failed',
    owner: ME, announced: false, orphanAnnounced: false,
    summary: 'india summary',
  })
  await pollOnce($, clock)
  expect(world.submits).toHaveLength(2)
  expect(world.toasts).toHaveLength(1)
  expect(world.toasts[0]).toContain('india')
  expect(world.toasts[0]).toContain('failed')
  expect(world.toasts[0]).not.toContain('\n')
  await pollOnce($, clock)
  expect(world.submits).toHaveLength(2)
  expect(world.toasts).toHaveLength(1)
  expectStateShape(world)
})

test('two overlapping polls submit a lane once', async ($, on) => {
  const { world, clock } = setup(on)
  await begin($, clock)

  world.lanes.push({
    id: 'lane-3', label: 'gamma', status: 'done',
    owner: ME, announced: false, orphanAnnounced: false,
    summary: 'gamma summary',
  })

  let release!: () => void
  world.gate = new Promise<void>(resolve => { release = resolve })
  const before = world.statusJsonCalls
  const p1 = $.tool.call({ tool: 'mcp__muse__lane_status' })
  const p2 = $.tool.call({ tool: 'mcp__muse__lane_status' })
  await Promise.all([p1, p2])
  // Both polls ran their guard check by now: answer() returns only after its
  // poll() started. Release the first status fetch.
  release()
  world.gate = null
  await clock.settle()

  expect(world.submits).toHaveLength(1)
  expect(world.submits[0]).toContain('gamma summary')
  // The second poll saw the first in flight and issued no fetch of its own.
  expect(world.statusJsonCalls - before).toBe(1)
  await pollOnce($, clock)
  expect(world.submits).toHaveLength(1)
  expectStateShape(world)
})

test('status line shows owned running lanes and clears', async ($, on) => {
  const { world, clock } = setup(on)
  await begin($, clock)
  expect(world.statuses.at(-1)).toBe(undefined)

  world.lanes.push(
    { id: 'lane-4', label: 'delta', status: 'running', owner: ME, announced: false, orphanAnnounced: false },
    { id: 'lane-5', label: 'echo', status: 'retry_wait', owner: ME, announced: false, orphanAnnounced: false },
    { id: 'lane-6', label: 'foxtrot', status: 'running', owner: OTHER, announced: false, orphanAnnounced: false },
    { id: 'lane-7', label: 'golf', status: 'queued', owner: ME, announced: false, orphanAnnounced: false },
  )
  await pollOnce($, clock)
  expect(world.statuses.at(-1)).toBe('muse: 2 running')

  world.lanes[0]!.status = 'done'
  world.lanes[0]!.summary = 'delta summary'
  await pollOnce($, clock)
  expect(world.statuses.at(-1)).toBe('muse: echo step:1')

  world.lanes[1]!.status = 'done'
  world.lanes[1]!.summary = 'echo summary'
  await pollOnce($, clock)
  expect(world.statuses.at(-1)).toBe(undefined)
  expect(world.submits).toHaveLength(2)
  await pollOnce($, clock)
  expect(world.submits).toHaveLength(2)
  expectStateShape(world)
})

test('lane_start writes a unique brief path per inline prompt', async ($, on) => {
  const { world, clock } = setup(on)
  await begin($, clock)

  for (let i = 0; i < 4; i++) {
    const r = await callMcp($, {
      tool: 'mcp__muse__lane_start',
      cwd: '/tmp/work',
      steps: [{ prompt: `brief ${i}` }],
    })
    expect(r.isError).toBeFalsy()
    expect(r.result).toContain('lane-new-')
    await clock.settle()
  }

  expect(world.writes).toHaveLength(4)
  const paths = world.writes.map(w => w.path)
  expect(new Set(paths).size).toBe(4)
  for (const p of paths) expect(p.startsWith('/tmp/fake-lanes-root/_briefs/')).toBe(true)
  expect(world.startArgs).toHaveLength(4)
  for (let i = 0; i < 4; i++) {
    expect(world.startArgs[i]).toContain(paths[i])
    expect(world.startArgs[i]).toContain('--owner-session')
    expect(world.startArgs[i]).toContain(ME)
  }
  expectStateShape(world)
})

test('poll uses the active view and lane_status pages older lanes', async ($, on) => {
  const { world, clock } = setup(on)
  await begin($, clock)

  world.lanes.push(
    {
      id: 'lane-live', label: 'live', status: 'running',
      owner: ME, announced: false, orphanAnnounced: false, phase: 'gate1',
    },
    {
      id: 'lane-old', label: 'old', status: 'done',
      owner: ME, announced: true, orphanAnnounced: false,
      summary: 'old summary',
      updatedAt: new Date(Date.now() - 2 * 24 * 3600 * 1000).toISOString(),
    },
  )
  await pollOnce($, clock)
  expect(world.runs.some(r => r === 'status --json --active')).toBe(true)
  expect(world.store.get('muse/lanes')).toEqual([rowJson(world.lanes[0]!)])
  expect(world.submits).toHaveLength(0)
  expect(world.statuses.at(-1)).toBe('muse: live gate1')

  const active = await callMcp($, { tool: 'mcp__muse__lane_status' })
  expect(active.isError).toBeFalsy()
  expect(active.result).toContain('lane-live')
  expect(active.result).toContain('older lanes')
  expect(active.result).not.toContain('lane-old')
  await clock.settle()

  const all = await callMcp($, { tool: 'mcp__muse__lane_status', all: true })
  expect(all.isError).toBeFalsy()
  expect(all.result).toContain('lane-live')
  expect(all.result).toContain('lane-old')
  expect(all.result).not.toContain('older lanes')
})

test('review_failed wakes the owner like failed', async ($, on) => {
  const { world, clock } = setup(on)
  await begin($, clock)

  world.lanes.push({
    id: 'lane-r', label: 'rev', status: 'review_failed',
    owner: ME, announced: false, orphanAnnounced: false,
    summary: 'Muse pre-review (not the independent review)\nRound 1: FAIL',
  })
  await pollOnce($, clock)
  expect(world.submits).toHaveLength(1)
  expect(world.submits[0]).toContain('review_failed')
  expect(world.submits[0]).toContain('Muse pre-review (not the independent review)')
  expect(world.toasts).toHaveLength(1)
  await pollOnce($, clock)
  expect(world.submits).toHaveLength(1)
  expectStateShape(world)
})

test('lane_start passes review and consult_max to the runner', async ($, on) => {
  const { world, clock } = setup(on)
  await begin($, clock)

  const r1 = await callMcp($, {
    tool: 'mcp__muse__lane_start',
    cwd: '/tmp/work',
    steps: [{ prompt: 'do it' }],
    review: { brief: 'allowlist: src/', rounds: 2 },
    consult_max: 5,
  })
  expect(r1.isError).toBeFalsy()
  await clock.settle()
  const r2 = await callMcp($, {
    tool: 'mcp__muse__lane_start',
    cwd: '/tmp/work',
    steps: [{ prompt: 'do it' }],
    review: true,
  })
  expect(r2.isError).toBeFalsy()
  await clock.settle()
  const r3 = await callMcp($, {
    tool: 'mcp__muse__lane_start',
    cwd: '/tmp/work',
    steps: [{ prompt: 'do it' }],
    review: { rounds: 0 },
  })
  expect(r3.isError).toBeFalsy()
  await clock.settle()

  expect(world.startArgs).toHaveLength(3)
  expect(world.startArgs[0]).toContain('--review')
  expect(world.startArgs[0]).toContain('--review-brief')
  expect(world.startArgs[0]).toContain('allowlist: src/')
  expect(world.startArgs[0]).toContain('--review-rounds')
  expect(world.startArgs[0]).toContain('2')
  expect(world.startArgs[0]).toContain('--consult-max')
  expect(world.startArgs[0]).toContain('5')
  expect(world.startArgs[1]).toContain('--review')
  expect(world.startArgs[1]).not.toContain('--review-brief')
  expect(world.startArgs[2]).toContain('--review-rounds')
  expect(world.startArgs[2]).toContain('0')
  expectStateShape(world)
})

test('stacked polls behind a slow status issue one fetch', async ($, on) => {
  const { world, clock } = setup(on)
  await begin($, clock)

  world.lanes.push({
    id: 'lane-slow', label: 'slow', status: 'done',
    owner: ME, announced: false, orphanAnnounced: false,
    summary: 'slow summary',
  })

  // One 38 s status fetch in flight while ticks keep firing: every later
  // poll must skip instead of stacking a fetch of its own.
  let release!: () => void
  world.gate = new Promise<void>(resolve => { release = resolve })
  const before = world.statusJsonCalls
  const calls = Array.from({ length: 6 }, () => $.tool.call({ tool: 'mcp__muse__lane_status' }))
  await Promise.all(calls)
  release()
  world.gate = null
  await clock.settle()

  expect(world.submits).toHaveLength(1)
  expect(world.submits[0]).toContain('slow summary')
  expect(world.statusJsonCalls - before).toBe(1)
  await pollOnce($, clock)
  expect(world.submits).toHaveLength(1)
  expectStateShape(world)
})

test('lanes ending in one poll wake once with a digest', async ($, on) => {
  const { world, clock } = setup(on)
  await begin($, clock)

  world.lanes.push(
    { id: 'lane-a', label: 'alpha', status: 'done', owner: ME, announced: false, orphanAnnounced: false, summary: 'alpha full',
      evidence: { branch: 'lane/alpha', head: 'abcdef1234567', head_start: '0123456789ab', commits: 2, accept_log: '/l/a/accept.log', review_files: [], summary_path: '/l/a/summary.md' } },
    { id: 'lane-b', label: 'bravo', status: 'failed', owner: ME, announced: false, orphanAnnounced: false, summary: 'bravo full',
      needsLead: { seq: 1, kind: 'accept_failed_harness', detail: 'exit 5: NOT STARTED' } },
  )
  await pollOnce($, clock)
  expect(world.submits).toHaveLength(1)
  const d = world.submits[0]!
  expect(d).toContain('Muse: 2 lane events.')
  expect(d).toContain('lane-a')
  expect(d).toContain('READY TO MERGE: lane/alpha')
  expect(d).toContain('lane-b')
  expect(d).toContain('accept_failed_harness: exit 5: NOT STARTED')
  expect(d).not.toContain('alpha full')
  expect(world.toasts).toEqual(['Muse lane bravo: failed'])
  await pollOnce($, clock)
  expect(world.submits).toHaveLength(1)
  expect(world.store.get('muse/outbox')).toEqual([])
})

test('a live lane that needs the lead wakes once per needs-lead seq', async ($, on) => {
  const { world, clock } = setup(on)
  await begin($, clock)

  world.lanes.push({ id: 'lane-q', label: 'quebec', status: 'running', owner: ME, announced: false, orphanAnnounced: false })
  await pollOnce($, clock)
  expect(world.submits).toHaveLength(0)

  world.lanes[0]!.needsLead = { seq: 1, kind: 'question', detail: 'change the accept to skip PlayMode?' }
  await pollOnce($, clock)
  expect(world.submits).toHaveLength(1)
  expect(world.submits[0]).toContain('needs the lead: question: change the accept to skip PlayMode?')
  expect(world.submits[0]).toContain('lane_answer')
  expect(world.toasts).toHaveLength(1)
  expect(world.notifies).toHaveLength(1)
  expect(world.statuses.at(-1)).toBe('muse: 1 running · 1 need lead')
  await pollOnce($, clock)
  expect(world.submits).toHaveLength(1)
  expect(world.ackCalls.filter(c => c === 'ack lane-q --lead 1')).toHaveLength(1)

  world.lanes[0]!.needsLead = { seq: 2, kind: 'box_wait_timeout', detail: 'gpu-6 queued 31m' }
  await pollOnce($, clock)
  expect(world.submits).toHaveLength(2)
  expect(world.submits[1]).toContain('box_wait_timeout')
  expect(world.submits[1]).toContain('box}')
  await pollOnce($, clock)
  expectStateShape(world)
})

test('a dropped wake stays in the outbox and goes out on the next poll', async ($, on) => {
  const { world, clock } = setup(on)
  await begin($, clock)

  world.dropNext = 1
  world.lanes.push({ id: 'lane-d', label: 'delta', status: 'done', owner: ME, announced: false, orphanAnnounced: false, summary: 'delta summary' })
  await pollOnce($, clock)
  expect(world.submits).toHaveLength(0)
  expect((world.store.get('muse/outbox') as unknown[]).length).toBe(1)

  // No retry before the pause is over.
  await pollOnce($, clock)
  expect(world.submits).toHaveLength(0)
  await clock.advance(21_000)
  await pollOnce($, clock)
  expect(world.submits).toHaveLength(1)
  expect(world.submits[0]).toContain('delta summary')
  expect(world.store.get('muse/outbox')).toEqual([])
  expect(world.ackCalls.filter(c => c === 'ack lane-d')).toHaveLength(1)
})

test('lane_start passes scope, box and advisor, and says how to open the pane when it is not placed', async ($, on) => {
  const { world, clock } = setup(on)
  await begin($, clock)

  world.placed = false
  const r = await callMcp($, {
    tool: 'mcp__muse__lane_start',
    cwd: '/tmp/work',
    steps: [{ prompt: 'do it' }],
    scope: ['Assets/Scripts/**', 'docs/*.md'],
    box: 'simgoodie-gpu-3',
    advisor: { model: 'opus', max: 2 },
  })
  await clock.settle()
  expect(r.isError).toBeFalsy()
  expect(r.result).toContain('/muse')
  const a = world.startArgs[0]!
  expect(a.join(' ')).toContain('--scope Assets/Scripts/** --scope docs/*.md')
  expect(a.join(' ')).toContain('--box simgoodie-gpu-3')
  expect(a.join(' ')).toContain('--advisor-model opus --advisor-max 2')
  expect(world.opens).toBe(1)

  world.placed = true
  const r2 = await callMcp($, { tool: 'mcp__muse__lane_start', cwd: '/tmp/work', steps: [{ prompt: 'x' }], advisor: {} })
  await clock.settle()
  expect(r2.result).not.toContain('/muse')
  expect(world.startArgs[1]!.join(' ')).toContain('--advisor-model sonnet')
  expect(world.startArgs[1]!).not.toContain('--advisor-max')
})

test('lane_answer passes text and box, and refuses an empty answer', async ($, on) => {
  const { world, clock } = setup(on)
  await begin($, clock)
  world.lanes.push({ id: 'lane-q', label: 'quebec', status: 'running', owner: ME, announced: false, orphanAnnounced: false })

  const empty = await callMcp($, { tool: 'mcp__muse__lane_answer', id: 'lane-q' })
  expect(empty.isError).toBe(true)
  const r = await callMcp($, { tool: 'mcp__muse__lane_answer', id: 'lane-q', text: 'keep PlayMode', box: 'gpu-2' })
  await clock.settle()
  expect(r.isError).toBeFalsy()
  expect(world.runs).toContain('answer lane-q --text=keep PlayMode --box gpu-2')
})

test('the pane flags a lane needing the lead, shows boxes, and expands a row on press', async ($, on) => {
  const { world, clock } = setup(on)
  await begin($, clock)
  world.lanes.push(
    { id: 'lane-r', label: 'romeo', status: 'running', owner: ME, announced: false, orphanAnnounced: false, box: 'gpu-3' },
    { id: 'lane-s', label: 'sierra', status: 'running', owner: ME, announced: false, orphanAnnounced: false,
      needsLead: { seq: 1, kind: 'scope_violation', detail: 'ProjectSettings/x.asset' } },
  )
  world.boxes = [{ box: 'gpu-3', holder_lane: 'lane-r', queue: ['lane-r'], lease: { who: 'lead', what: 'R16 gate', since: '2026-11-06T10:00:00Z' } }]
  await pollOnce($, clock)

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({
      plugin: 'muse', component: 'Pane', requestId: 'muse-lanes', surface,
      props: { title: 'Muse lanes', isFocused: false, bodyColumns: 100, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} },
    })
    expect((await ui.find({ type: 'Text', text: /2 running · 1 need lead/ }))).toBeTruthy()
    expect((await ui.find({ type: 'Text', text: /gpu-3: romeo · lease lead: R16 gate/ }))).toBeTruthy()
    expect((await ui.find({ type: 'Text', text: /needs lead: scope_violation: ProjectSettings\/x.asset/ }))).toBeTruthy()
    await ui.unmount()
  }

  const ui = await $.ui.mount({
    plugin: 'muse', component: 'Pane', requestId: 'muse-lanes', surface: 'terminal',
    props: { title: 'Muse lanes', isFocused: false, bodyColumns: 100, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} },
  })
  await ui.press({ key: 'row-lane-r' })
  await clock.settle()
  expect(world.runs).toContain('status lane-r')
  expect((world.store.get('muse/expanded') as Record<string, boolean>)['lane-r']).toBe(true)
  expect((world.store.get('muse/details') as Record<string, string>)['lane-r']).toContain('status: running')
  await ui.unmount()
})

test('an event is queued in the outbox before the runner ack claims it', async ($, on) => {
  const { world, clock } = setup(on)
  await begin($, clock)

  world.lanes.push(
    { id: 'lane-o', label: 'oscar', status: 'done', owner: ME, announced: false, orphanAnnounced: false, summary: 'oscar summary' },
    { id: 'lane-p', label: 'papa', status: 'running', owner: ME, announced: false, orphanAnnounced: false,
      needsLead: { seq: 4, kind: 'question', detail: 'which box?' } },
  )
  await pollOnce($, clock)
  expect(world.ackCalls).toEqual(['ack lane-o', 'ack lane-p --lead 4'])
  expect(world.outboxAtAck[0]).toContain('lane-o:end:0')
  expect(world.outboxAtAck[1]).toContain('lane-p:lead:4')
  expect(world.submits).toHaveLength(1)
})
