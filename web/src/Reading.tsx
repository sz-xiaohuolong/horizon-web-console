import { useEffect, useState } from 'react'
import { BookOpen, Check, Download, KeyRound, QrCode, Radio, RefreshCw, Search } from 'lucide-react'
import { Badge, Button, Empty, ErrorBox, Markdown, Notice, PageTitle, SectionHead, Skeleton } from './components'
import { api, dateTime, download } from './lib'
import { useResource } from './hooks'
import { ReportDelivery } from './ReportDelivery'
import type { Login, Summary, Wechat } from './types'

type Update = (changes: Record<string, string | null>, replace?: boolean) => void
export function SummariesPage({ query, update }: { query: URLSearchParams; update: Update }) {
  const list = useResource<{ items: Summary[]; count: number }>('/api/summaries', 5000)
  const [term, setTerm] = useState('')
  const language = query.get('lang') || ''
  const date = query.get('date') || ''
  const items = (list.data?.items || []).filter(s => (!language || s.language === language) && (!date || s.date === date) && (!term || `${s.title} ${s.date}`.toLowerCase().includes(term.toLowerCase())))
  const id = items.some(s => s.id === query.get('summary')) ? query.get('summary') : items[0]?.id
  const selected = items.find(s => s.id === id)
  const document = useResource<Summary & { markdown: string }>(id ? `/api/summaries/${encodeURIComponent(id)}?revision=${encodeURIComponent(selected?.revision || '')}` : null)
  const refresh = () => { list.reload(); document.reload() }
  const categories = [...(document.data?.markdown || '').matchAll(/^##\s+(.+)$/gm)].map(m => m[1].trim())
  const category = categories.includes(query.get('category') || '') ? query.get('category') || '' : ''
  const fullText = document.data?.markdown || ''
  const shownText = category ? fullText.split(/(?=^##\s)/m).filter((section, i) => i === 0 || section.split('\n')[0].replace(/^##\s+/, '').trim() === category).join('\n') : fullText
  return <><PageTitle title="历史速递" description="按最近更新时间排列；同一天同语言展示最新版本，各次运行的版本可在运行记录中查看。" actions={<Button onClick={refresh}><RefreshCw size={15} />刷新归档</Button>} />
    {list.error && <ErrorBox message={list.error} retry={list.reload} />}
    <div className="archive-filters"><label className="search-field"><Search size={16} /><input aria-label="搜索速递标题或日期" type="search" placeholder="搜索速递标题或日期" value={term} onChange={e => setTerm(e.target.value)} /></label><label>日期<input type="date" aria-label="按日期筛选" value={date} onChange={e => update({ date: e.target.value || null, summary: null, category: null })} /></label><label>语言<select value={language} onChange={e => update({ lang: e.target.value || null, summary: null, category: null })}><option value="">所有语言</option>{[...new Set((list.data?.items || []).map(s => s.language))].map(lang => <option key={lang} value={lang}>{lang === 'zh' ? '简体中文' : lang === 'en' ? '英语' : lang}</option>)}</select></label>{(language || date || term) && <Button onClick={() => { setTerm(''); update({ date: null, lang: null, summary: null, category: null }) }}>清除筛选</Button>}</div>
    {list.loading ? <Skeleton rows={5} /> : !items.length ? <Empty title={list.data?.count ? '没有匹配的速递' : '还没有生成速递'}>{list.data?.count ? '请调整日期、语言或搜索条件。' : '运行流水线后，Markdown 报告会自动归档。已有文件保存在本机 data/summaries 目录。'}</Empty> : <div className="archive-layout"><aside className="archive-picker" aria-label="选择速递"><div className="run-picker-title">速递归档<span>{items.length} 份</span></div>{items.map(s => <button type="button" key={s.id} className={s.id === id ? 'selected' : ''} onClick={() => update({ summary: s.id, category: null })} aria-pressed={s.id === id}><span className="summary-date"><BookOpen size={15} />{s.date}<span>{s.language === 'zh' ? '中文' : s.language === 'en' ? '英语' : s.language}</span></span><strong>{s.title}</strong>{s.updated_at && <small>更新于 {dateTime(s.updated_at)}</small>}</button>)}</aside><section className="reading-panel">
      {document.loading ? <Skeleton rows={6} /> : document.error ? <ErrorBox message={document.error} retry={document.reload} /> : document.data && <><div className="reading-toolbar"><span>{document.data.date} / {document.data.language === 'zh' ? '简体中文' : document.data.language}{document.data.updated_at && <small> · 更新于 {dateTime(document.data.updated_at)}</small>}</span><Button onClick={() => download(document.data!.id, fullText, 'text/markdown;charset=utf-8')}><Download size={15} />下载 Markdown</Button></div><ReportDelivery key={`${document.data.id}:${document.data.revision}`} id={document.data.id} revision={document.data.revision} />{categories.length > 1 && <div className="category-filter"><label>报告章节<select value={category} onChange={e => update({ category: e.target.value || null })}><option value="">全部章节</option>{categories.map(c => <option key={c} value={c}>{c}</option>)}</select></label></div>}<Markdown text={shownText} /></>}
    </section></div>}
  </>
}

const loginTitles: Record<string, string> = {
  waiting: '等待扫码', scanned: '请在手机上确认', scaned: '请在手机上确认', confirmed: '扫码已确认',
  waiting_message: '等待首条消息', ready: '连接已就绪', expired: '二维码已过期', failed: '连接未完成', cancelled: '登录已取消',
}
export function WechatPage({ onChanged }: { onChanged: () => void }) {
  const status = useResource<Wechat & { logged_in_at?: string; context_updated_at?: string }>('/api/wechat', 5000)
  const [loginId, setLoginId] = useState(() => sessionStorage.getItem('horizon-wechat-login') || '')
  const login = useResource<Login>(loginId ? `/api/wechat/login/${encodeURIComponent(loginId)}` : null, 2000)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [code, setCode] = useState('')
  const d = status.data
  const current = login.data
  const terminal = current && ['ready', 'expired', 'failed', 'cancelled'].includes(current.status)
  useEffect(() => { if (current?.status === 'ready') { status.reload(); onChanged() } }, [current?.status])
  const action = async (url: string, body?: unknown) => {
    setBusy(true); setError(''); setMessage('')
    try {
      const result = await api<any>(url, { method: 'POST', ...(body ? { body: JSON.stringify(body) } : {}) })
      if (result.login_id) { setLoginId(result.login_id); sessionStorage.setItem('horizon-wechat-login', result.login_id); login.setData(result); login.reload() }
      else { status.setData(result); setMessage(result.ready ? '会话已就绪，可在历史速递中选择报告并手动推送。' : '尚未收到新消息。请先在微信中给机器人发一条消息，再刷新。') }
      status.reload(); onChanged()
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  return <><PageTitle title="微信连接" description="扫码连接本机会话，随时检查可用状态与回复额度。" />
    {status.error && <ErrorBox message={status.error} retry={status.reload} />}{error && <ErrorBox message={error} />}{message && <div className="notice" role="status">{message}</div>}
    {status.loading && !d ? <Skeleton rows={4} /> : <div className="wechat-layout"><section className="connection-panel"><SectionHead title="会话状态" aside={<Badge status={d?.ready ? 'ready' : 'unknown'}>{d?.ready ? '已就绪' : d?.connected ? '等待上下文' : '未连接'}</Badge>} /><div className="connection-symbol"><Radio size={30} strokeWidth={1.4} /><div><h3>{d?.ready ? '连接已准备好' : d?.connected ? '已登录，等待消息' : '连接你的微信'}</h3><p>{d?.ready ? '可在历史速递页预览并确认推送报告。' : '在此管理连接，报告仅在手动确认后发送。'}</p></div></div>
      <dl className="connection-details"><div><dt>配置中的推送开关</dt><dd>{d?.enabled ? '已启用' : '已关闭'}</dd></div><div><dt>估算剩余额度</dt><dd className="budget-value">{d?.remaining_budget == null ? '未记录' : `${d.remaining_budget} / ${d.budget_limit}`}</dd></div>{d?.logged_in_at && <div><dt>登录时间</dt><dd>{dateTime(d.logged_in_at)}</dd></div>}{d?.context_updated_at && <div><dt>最近上下文更新</dt><dd>{dateTime(d.context_updated_at)}</dd></div>}</dl>
      {d?.remaining_budget != null && d.remaining_budget <= 2 && <Notice>估算剩余额度较低。向机器人发送一条新消息后，刷新会话以更新回复上下文。</Notice>}
      <p className="field-help">额度来自本地会话估算，实际发送结果以微信服务为准。新消息通常可更新上下文；过期会话需要重新扫码。</p>
      <div className="connection-actions"><Button primary onClick={() => action('/api/wechat/login')} disabled={busy || !!current && !terminal}><QrCode size={16} />{busy ? '处理中…' : d?.connected ? '重新扫码连接' : '获取登录二维码'}</Button><Button onClick={() => action('/api/wechat/refresh')} disabled={busy || !d?.connected}><RefreshCw size={16} />刷新消息上下文</Button></div>
    </section><section className="login-panel"><SectionHead title="连接步骤" /><ol className="connection-steps"><li><div><h3>获取二维码</h3><p>点击左侧按钮，再用微信扫码。</p></div></li><li><div><h3>在手机上确认</h3><p>如需验证码，按页面提示输入。</p></div></li><li><div><h3>给机器人发一条消息</h3><p>例如“你好”，然后刷新消息上下文。</p></div></li></ol>
      {login.error && <ErrorBox message={login.error} retry={login.reload} />}
      {current && <div className="qr-content"><div className="section-heading"><h3>{loginTitles[current.status] || current.status}</h3><Badge status={current.status}>{loginTitles[current.status] || current.status}</Badge></div>{current.qr_data_url && !terminal && <img className="qr-image" src={current.qr_data_url} alt="微信登录二维码，请使用手机微信扫描" width="232" height="232" />}<p role="status">{current.message}</p>{current.expires_at && !terminal && <small>过期时间 {dateTime(current.expires_at, true)}</small>}{current.verify_code && !terminal && <form className="verify-form" onSubmit={e => { e.preventDefault(); void action(`/api/wechat/login/${encodeURIComponent(loginId)}/verify`, { code }) }}><label>手机验证码<input value={code} onChange={e => setCode(e.target.value)} inputMode="numeric" autoComplete="one-time-code" required /></label><Button onClick={() => action(`/api/wechat/login/${encodeURIComponent(loginId)}/verify`, { code })} disabled={busy || !code.trim()}><KeyRound size={15} />提交验证码</Button></form>}{!terminal && <Button onClick={() => action(`/api/wechat/login/${encodeURIComponent(loginId)}/cancel`)} disabled={busy}>取消登录</Button>}{current.status === 'ready' && <span className="ready-label"><Check size={16} />会话已保存到本机</span>}</div>}
    </section></div>}
  </>
}
