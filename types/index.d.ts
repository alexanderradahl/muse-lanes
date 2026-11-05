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
}

declare module 'claude-code' {
  interface PluginState {
    muse: {
      lanes: MuseLane[]
      summaryTries: Record<string, number>
    }
  }
}
