import type { Json } from './types'

const names: Record<string, string> = {
  github: 'GitHub', hackernews: 'Hacker News', rss: 'RSS 订阅', reddit: 'Reddit',
  telegram: 'Telegram', twitter: 'X / Twitter', openbb: 'OpenBB',
  ossinsight: 'OSS Insight', gdelt: 'GDELT', google_news: 'Google 新闻',
}
export const sourceName = (value: string) => names[value] || value || '未知来源'
export const number = (value: number | null | undefined) => value == null ? '—' : value.toLocaleString('zh-CN')
export const duration = (seconds: number | null | undefined) => {
  if (seconds == null) return '未记录'
  const n = Math.max(0, Math.round(seconds))
  return n >= 60 ? `${Math.floor(n / 60)} 分 ${n % 60} 秒` : `${n} 秒`
}
export const dateTime = (value?: string | null, short = false) => {
  if (!value) return '未记录'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleString('zh-CN', short
    ? { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }
    : { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
}
export const safeUrl = (value?: string): string | undefined => {
  if (!value) return undefined
  try { const u = new URL(value); return ['http:', 'https:'].includes(u.protocol) ? u.href : undefined } catch { return undefined }
}
export const itemAnalysis = (item: Json): Json => item.processing?.analysis || {}
export function patchSource<T extends Record<string, any>>(sources: T, kind: string, index: number | null, patch: Json): T {
  const copy = structuredClone(sources)
  if (index == null) copy[kind as keyof T] = { ...copy[kind], ...patch }
  else copy[kind as keyof T] = copy[kind].map((item: Json, i: number) => i === index ? { ...item, ...patch } : item)
  return copy
}
export function formatApiError(body: Json, status: number): string {
  if (typeof body.detail === 'string') return body.detail
  if (typeof body.error?.message === 'string') return body.error.message
  if (typeof body.message === 'string') return body.message
  if (Array.isArray(body.detail)) return `输入未通过校验：${body.detail.map((v: Json) => `${v.loc?.slice(1).join('.') || '参数'} ${v.msg || '格式不正确'}`).join('；')}`
  return status === 409 ? '当前状态已变化，请刷新后重试。' : `请求未完成（${status}），请重试或检查服务日志。`
}
export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message) }
}
export async function api<T>(url: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(url, { ...init, headers: { 'Content-Type': 'application/json', 'X-Horizon-Request': '1', ...init.headers } })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new ApiError('无法连接本地服务。请确认 Horizon Web 已启动，然后重试。', 0)
  }
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new ApiError(formatApiError(body, response.status), response.status)
  return body as T
}
export function download(name: string, text: string, type = 'text/plain;charset=utf-8') {
  const url = URL.createObjectURL(new Blob([text], { type }))
  const link = document.createElement('a'); link.href = url; link.download = name; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
export const statusNames: Record<string, string> = {
  running: '运行中', completed: '已完成', failed: '失败', cancelled: '已取消',
  interrupted: '已中断', unknown: '历史记录', pending: '等待中',
}
export const stages = [
  { id: 'raw', name: '采集', hint: '原始信息' },
  { id: 'scored', name: '评分', hint: 'AI 相关性' },
  { id: 'filtered', name: '筛选', hint: '去重与配额' },
  { id: 'enriched', name: '补充', hint: '深度上下文' },
] as const
