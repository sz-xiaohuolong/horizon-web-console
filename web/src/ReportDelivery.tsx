import { useRef, useState } from 'react'
import { Send } from 'lucide-react'
import { Button, ErrorBox } from './components'
import { api } from './lib'

type Result = { status: string; chunks_sent: number; message: string }
type Preview = { revision: string; confirmation: string; chunk_count: number; remaining_budget: number; can_send: boolean; reason: string; delivery?: Result }

export function ReportDelivery({ id, revision }: { id: string; revision: string }) {
  const [preview, setPreview] = useState<Preview | null>(null)
  const [result, setResult] = useState<Result | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const sending = useRef(false)
  const url = `/api/summaries/${encodeURIComponent(id)}/wechat`
  const inspect = async () => {
    setBusy(true); setError('')
    try {
      const next = await api<Preview>(url)
      if (next.revision !== revision) throw new Error('报告已有新版本，请刷新归档后重新推送。')
      setPreview(next); setResult(next.delivery || null)
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  const send = async () => {
    if (!preview?.can_send || sending.current) return
    sending.current = true
    setBusy(true); setError('')
    try {
      setResult(await api<Result>(url, { method: 'POST', body: JSON.stringify({ revision: preview.revision, confirmation: preview.confirmation }) }))
      setPreview(null)
    } catch (e) {
      setError(`${(e as Error).message} 请检查发送状态，不要直接重复发送。`)
      setPreview(null)
    } finally { sending.current = false; setBusy(false) }
  }
  return <section className="report-delivery" aria-label="微信推送">
    {!preview && !result && <Button onClick={inspect} disabled={busy}><Send size={15} />{busy ? '正在检查…' : error ? '检查发送状态' : '推送到微信'}</Button>}
    {error && <ErrorBox message={error} />}
    {preview && !result && <div className="delivery-preview" aria-live="polite">
      <h3>推送这份完整报告</h3>
      <p>将发送到当前连接的微信会话，共 {preview.chunk_count} 段；估算剩余额度 {preview.remaining_budget} 条。</p>
      <p className="field-help">包含全部章节。确认后开始发送，实际送达以微信为准。</p>
      {!preview.can_send && <p>{preview.reason}</p>}
      <div className="connection-actions"><Button primary onClick={send} disabled={busy || !preview.can_send}>{busy ? '正在发送…' : `确认发送 ${preview.chunk_count} 段`}</Button><Button onClick={() => setPreview(null)} disabled={busy}>取消推送</Button></div>
    </div>}
    {result && <div className="notice" role="status"><p>{result.message}</p></div>}
  </section>
}
