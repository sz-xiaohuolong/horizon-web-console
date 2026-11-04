export type Stage = 'raw' | 'scored' | 'filtered' | 'enriched'
export type Json = Record<string, any>
export interface Run {
  run_id: string; status: string; current_stage: string | null
  created_at: string; updated_at?: string; duration_seconds: number | null
  tokens: { input: number; output: number; total: number } | null
  counts: Record<Stage, number | null>; stages: Record<Stage, boolean>
  stage_durations: Record<string, number>; error: string | null; meta: Json
}
export interface Source { id: string; name: string; enabled: boolean; count: number }
export interface Wechat {
  enabled: boolean; connected: boolean; ready: boolean
  remaining_budget: number | null; budget_limit: number; message?: string
}
export interface Overview {
  active_run: Run | null; latest_run: Run | null; run_count: number; summary_count: number
  sources: Source[]; ai: { provider: string; model: string; configured: boolean }
  wechat: Wechat; scheduler: { managed: boolean; message: string }; warnings: string[]; busy?: boolean
}
export interface Summary { id: string; date: string; language: string; title: string; size: number; revision: string; updated_at?: string }
export interface StageData {
  items: Json[]; total: number; offset: number; limit: number
  score_distribution: Record<string, number>; source_counts: Record<string, number>
}
export interface ConfigData {
  revision: string; config: Json
  profiles: { id: string; name: string; threshold: number | null; topic_dedup: boolean }[]
}
export interface Log { id: number; time: string; level: string; message: string }
export interface Login {
  login_id: string; status: string; qr_data_url?: string; expires_at?: string
  message: string; verify_code?: boolean
}
