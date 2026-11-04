import { useState, type ReactNode } from 'react'
import { AlertCircle, Check, ChevronDown, ExternalLink, Inbox, RefreshCw, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { dateTime, duration, itemAnalysis, number, safeUrl, sourceName, stages, statusNames } from './lib'
import type { Json, Run, Stage } from './types'

export function Button({ children, primary = false, small = false, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { primary?: boolean; small?: boolean }) {
  return <button type="button" className={`button${primary ? ' primary' : ''}${small ? ' small' : ''}`} {...props}>{children}</button>
}
export function Badge({ status, children }: { status?: string; children?: ReactNode }) {
  const tone = ['completed', 'ready', 'success'].includes(status || '') ? 'ok' : ['failed', 'error'].includes(status || '') ? 'bad' : ['running', 'waiting', 'scanned'].includes(status || '') ? 'accent' : 'muted'
  return <span className={`badge ${tone}`}>{status === 'running' && <RefreshCw size={12} />} {children || statusNames[status || ''] || status}</span>
}
export function ErrorBox({ message, retry }: { message: string; retry?: () => void }) {
  return <div className="notice error" role="alert"><AlertCircle size={18} /><div><p>{message}</p>{retry && <button type="button" className="text-button" onClick={retry}>重试</button>}</div></div>
}
export function Notice({ children }: { children: ReactNode }) {
  return <div className="notice"><AlertCircle size={17} /><div>{children}</div></div>
}
export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return <div className="empty"><Inbox size={29} strokeWidth={1.25} /><h3>{title}</h3><p>{children}</p>{action}</div>
}
export function Skeleton({ rows = 3 }: { rows?: number }) {
  return <div className="skeleton" role="status" aria-label="正在加载"><span className="visually-hidden">正在加载数据</span>{Array.from({ length: rows }, (_, i) => <div key={i} />)}</div>
}
export function PageTitle({ title, description, actions }: { title: string; description: string; actions?: ReactNode }) {
  return <div className="page-heading"><div><h1>{title}</h1><p>{description}</p></div>{actions && <div className="heading-actions">{actions}</div>}</div>
}
export function SectionHead({ title, children, aside }: { title: string; children?: ReactNode; aside?: ReactNode }) {
  return <div className="section-heading"><div><h2>{title}</h2>{children && <p>{children}</p>}</div>{aside}</div>
}
export function Pipeline({ run, selected, onSelect }: { run: Run | null; selected?: Stage; onSelect: (stage: Stage) => void }) {
  return <div className="pipeline" aria-label="流水线阶段">{stages.map((stage, index) => {
    const available = run?.stages?.[stage.id]
    const current = run?.status === 'running' && run.current_stage === stage.id
    return <button type="button" key={stage.id} className={`stage${selected === stage.id ? ' selected' : ''}${current ? ' current' : ''}`} onClick={() => onSelect(stage.id)} disabled={!available && !current} aria-label={`查看${stage.name}阶段`} aria-pressed={selected === stage.id}>
      <span className="stage-label"><span className="stage-number">{index + 1}</span>{stage.name}{available && <Check size={14} />}</span>
      <strong>{number(run?.counts?.[stage.id])}<small>条</small></strong>
      <span className="stage-hint">{current ? '正在处理' : run?.stage_durations?.[stage.id] != null ? duration(run.stage_durations[stage.id]) : stage.hint}</span>
    </button>
  })}</div>
}
export function RunTable({ runs, select }: { runs: Run[]; select: (run: Run) => void }) {
  if (!runs.length) return <Empty title="还没有可观测的运行">从右上角发起一次运行，即可在这里追踪阶段和结果。旧 CLI 摘要仍可在历史速递中阅读。</Empty>
  return <div className="table-scroll"><table className="run-table"><thead><tr><th>运行时间</th><th>状态</th><th>采集 / 保留</th><th>耗时</th><th>Token</th><th><span className="visually-hidden">操作</span></th></tr></thead><tbody>{runs.map(run => <tr key={run.run_id}>
    <td><button type="button" className="row-link" onClick={() => select(run)}>{dateTime(run.created_at, true)}<span className="run-id">{run.run_id}</span></button></td>
    <td><Badge status={run.status} /></td><td className="measured">{number(run.counts?.raw)} <span className="muted">/</span> {number(run.counts?.filtered)}</td>
    <td>{duration(run.duration_seconds)}</td><td className="measured">{number(run.tokens?.total)}</td>
    <td><button type="button" className="text-button" onClick={() => select(run)} aria-label={`查看运行 ${run.run_id}`}>查看</button></td>
  </tr>)}</tbody></table></div>
}
export function ItemRow({ item }: { item: Json }) {
  const [open, setOpen] = useState(false)
  const analysis = itemAnalysis(item)
  const url = safeUrl(item.url)
  return <article className={`item-row${open ? ' expanded' : ''}`}>
    <div className="item-main"><span className={`score${analysis.score >= 7 ? ' high' : ''}`}>{analysis.score == null ? '—' : Number(analysis.score).toFixed(1)}</span><div className="item-text">
      <button type="button" className="item-title" aria-expanded={open} onClick={() => setOpen(!open)}>{item.title || '无标题信息'}<ChevronDown size={16} /></button>
      <div className="item-meta"><span>{sourceName(item.source_type)}</span>{item.profile && <span>{Array.isArray(item.profile) ? item.profile.join('、') : item.profile}</span>}<time>{dateTime(item.published_at, true)}</time>{item.retained === false && <span className="removed">未进入筛选结果</span>}</div>
    </div>{url && <a className="icon-button" href={url} target="_blank" rel="noreferrer" aria-label={`打开原文：${item.title}`}><ExternalLink size={16} /></a>}</div>
    {open && <div className="item-detail">
      <dl><dt>评分原因</dt><dd>{analysis.reason || '该阶段尚未记录评分原因。'}</dd>{analysis.summary && <><dt>内容摘要</dt><dd>{analysis.summary}</dd></>}{item.exclusion_reason && <><dt>筛除说明</dt><dd>{item.exclusion_reason} <span className="muted">（根据阶段工件推断）</span></dd></>}</dl>
      {Array.isArray(analysis.tags) && <div className="tags">{analysis.tags.map((tag: string) => <span key={tag}>{tag}</span>)}</div>}
      {item.content && <details><summary>查看采集原文</summary><p className="original-content">{item.content}</p></details>}
      {item.processing?.artifacts && <details><summary>查看深度补充工件</summary><pre>{JSON.stringify(item.processing.artifacts, null, 2)}</pre></details>}
    </div>}
  </article>
}
export function Markdown({ text }: { text: string }) {
  return <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml urlTransform={url => safeUrl(url) || (url.startsWith('#') ? url : '')} components={{
    a: ({ href, children }) => href ? <a href={href} target="_blank" rel="noreferrer">{children}</a> : <span>{children}</span>,
    img: ({ alt }) => <span className="muted">{alt ? `[图片：${alt}]` : '[远程图片已省略]'}</span>,
  }}>{text}</ReactMarkdown></div>
}
export function CloseButton({ onClick }: { onClick: () => void }) {
  return <button type="button" className="icon-button" onClick={onClick} aria-label="关闭"><X size={18} /></button>
}
