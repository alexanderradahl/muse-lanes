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
const TERMINAL = new Set(['done', 'failed', 'gave_up', 'stopped'])

type FakeLane = {
  id: string
  label?: string
  status: string
  owner: string | null
  announced: boolean
  orphanAnnounced: boolean
  summary?: string
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
}

// One row the way `muse-lane status --json` serves it.
function rowJson(l: FakeLane) {
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
  }
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
    if (cmd === 'status' && a === '--json') {
      world.statusJsonCalls += 1
      if (world.gate) await world.gate
      return runOk(JSON.stringify(world.lanes.map(rowJson)))
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
      const l = world.lanes.find(l => l.id === a)
      if (!l) return runFail(1, `muse-lane: unknown lane: ${a}`)
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
    world.submits.push(e.text)
    return { text: e.text }
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

test('owned lane end toasts alongside the wake-up', async ($, on) => {
  const { world, clock } = setup(on)
  await begin($, clock)

  world.lanes.push({
    id: 'lane-8', label: 'hotel', status: 'done',
    owner: ME, announced: false, orphanAnnounced: false,
    summary: 'hotel summary',
  })
  await pollOnce($, clock)
  expect(world.submits).toHaveLength(1)
  expect(world.toasts).toHaveLength(1)
  expect(world.toasts[0]).toContain('hotel')
  expect(world.toasts[0]).toContain('done')
  expect(world.toasts[0]).not.toContain('\n')
  await pollOnce($, clock)
  expect(world.submits).toHaveLength(1)
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
  expect(world.statuses.at(-1)).toBe('muse: 1 running')

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
