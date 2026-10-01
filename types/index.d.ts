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
}

declare module 'claude-code' {
  interface PluginState {
    muse: {
      lanes: MuseLane[]
      summaryTries: Record<string, number>
    }
  }
}
