export type NeedsLeadKind =
  | 'question'
  | 'review_failed'
  | 'accept_failed_code'
  | 'accept_failed_harness'
  | 'box_wait_timeout'
  | 'scope_violation'

export type MuseLane = {
  id: string
  label?: string
  cwd?: string
  status: string
  step?: number
  steps?: number
  attempt?: number
  commits?: number
  last_activity_at?: number | string
  reason?: string
  owner_session: string | null
  announced: boolean
  orphan_announced: boolean
  phase?: string | null
  phase_started?: number | string | null
  started_at?: number | string | null
  updated_at?: number | string | null
  stall_sec?: number | null
  last_subject?: string | null
  accept_tail?: string | null
  review_rounds?: Array<{ round?: number; verdict?: string }> | null
  review_error?: string | null
  // 0.3: absent on lanes written by an older runner.
  needs_lead?: { seq: number; kind: NeedsLeadKind; detail: string; at: string; step?: number } | null
  needs_lead_announced?: boolean
  box?: string | null
  box_state?: 'queued' | 'held' | null
  box_queued_at?: string | null
  branch?: string | null
  head?: string | null
  evidence?: {
    branch: string
    head: string
    head_start: string
    commits: number
    accept_log: string
    review_files: string[]
    summary_path: string
  } | null
  advisor_calls?: number
}

export type MuseBox = {
  box: string
  holder_lane: string | null
  queue: string[]
  lease: { who: string; what: string; since: string } | null
}

// A claimed event waiting for its prompt: `key` is `<id>:<kind>:<seq>`, `block` its digest entry.
export type MuseWake = {
  key: string
  id: string
  kind: 'end' | 'lead' | 'orphan'
  full: string
  block: string
  loud: boolean
}

declare module 'claude-code' {
  interface PluginState {
    muse: {
      lanes: MuseLane[]
      boxes: MuseBox[]
      expanded: Record<string, boolean>
      details: Record<string, string>
      outbox: MuseWake[]
      summaryTries: Record<string, number>
    }
  }
}
