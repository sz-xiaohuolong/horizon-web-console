import { useEffect, useRef, useState } from 'react'
import { Download, FileText, ListFilter, Pause, Play, Search, Square, Terminal } from 'lucide-react'
import { Badge, Button, Empty, ErrorBox, ItemRow, Markdown, Notice, PageTitle, Pipeline, Skeleton } from './components'
import { api, dateTime, download, duration, number, sourceName, stages } from './lib'
import { useDebounced, useResource } from './hooks'
import type { Log, Run, Stage, StageData } from './types'

type Update = (changes: Record<string, string | null>, replace?: boolean) => void
export function RunsPage({ query, update, onChanged, openRun }: { query: URLSearchParams; update: Update; onChanged: () => void; openRun: () => void }) {
  const runs = useResource<{ items: Run[]; count: number }>('/api/runs?limit=100', 5000)
  const runId = query.get('run') || runs.data?.items[0]?.run_id
  const detail = useResource<Run>(runId ? `/api/runs/${encodeURIComponent(runId)}` : null, 4000)
  const run = detail.data
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const stage = (stages.some(s => s.id === query.get('stage')) ? query.get('stage') : 'raw') as Stage
  const tab = query.get('detail') || 'stages'
  const cancel = async () => {
    if (!run || !window.confirm('取消当前运行？已生成的工件会保留，已发生的模型用量不会撤回。')) return
    setBusy(true); setError('')
    try { await api(`/api/runs/${encodeURIComponent(run.run_id)}/cancel`, { method: 'POST' }); detail.reload(); runs.reload(); onChanged() }
    catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  return <><PageTitle title="运行记录" description="检查阶段工件、追踪日志，理解每一次筛选。" actions={<Button onClick={runs.reload}>刷新记录</Button>} />
    {runs.error && <ErrorBox message={runs.error} retry={runs.reload} />}
    {runs.loading && !runs.data ? <Skeleton rows={5} /> : !runs.data?.items.length ? <Empty title="还没有运行记录" action={<Button primary onClick={openRun}>运行一次</Button>}>由 Web 发起的运行会在这里留下各阶段工件。旧 CLI 生成的 Markdown 请前往历史速递查看。</Empty> : <div className="runs-layout">
      <aside className="run-picker" aria-label="选择运行"><div className="run-picker-title">运行归档<span>{runs.data.count} 次</span></div>{runs.data.items.map(r => <button type="button" key={r.run_id} className={r.run_id === runId ? 'selected' : ''} aria-pressed={r.run_id === runId} onClick={() => update({ run: r.run_id, stage: 'raw', offset: null, q: null, source: null, disposition: null, min_score: null })}><span><time>{dateTime(r.created_at, true)}</time><Badge status={r.status} /></span><small className="measured">{r.run_id}</small><span className="run-picker-count">采集 {number(r.counts?.raw)} 条<span>保留 {number(r.counts?.filtered)} 条</span></span></button>)}</aside>
      <section className="run-workbench">
        {detail.error && <ErrorBox message={detail.error} retry={detail.reload} />}
        {detail.loading && !run ? <Skeleton rows={4} /> : run && <>
          <div className="run-heading"><div><h2>{dateTime(run.created_at)}<Badge status={run.status} /></h2><p className="measured">{run.run_id}</p></div><div className="inline-meta">{run.status === 'running' && <Button onClick={cancel} disabled={busy}><Square size={13} />{busy ? '正在取消…' : '取消运行'}</Button>}<button type="button" className="icon-button" aria-label="下载运行元信息" onClick={() => download(`${run.run_id}.json`, JSON.stringify(run, null, 2), 'application/json')}><Download size={17} /></button></div></div>
          {error && <ErrorBox message={error} />}{run.error && <ErrorBox message={run.error} />}
          {run.status === 'interrupted' && <Notice>运行因服务停止而中断，已有工件已保留。可检查日志后重新发起运行。</Notice>}
          <dl className="run-metrics"><div><dt>运行耗时</dt><dd>{duration(run.duration_seconds)}</dd></div><div><dt>输入 Token</dt><dd>{number(run.tokens?.input)}</dd></div><div><dt>输出 Token</dt><dd>{number(run.tokens?.output)}</dd></div><div><dt>保留条目</dt><dd>{number(run.counts?.filtered)}</dd></div></dl>
          <Pipeline run={run} selected={stage} onSelect={s => update({ stage: s, detail: 'stages', offset: null, ...(s === 'raw' ? { min_score: null } : {}), ...(!['raw', 'scored'].includes(s) ? { disposition: null } : {}) })} />
          <div className="view-tabs" aria-label="运行内容"><button type="button" aria-pressed={tab === 'stages'} onClick={() => update({ detail: 'stages' })}><ListFilter size={15} />阶段工件</button><button type="button" aria-pressed={tab === 'logs'} onClick={() => update({ detail: 'logs' })}><Terminal size={15} />{run.status === 'running' ? '实时日志' : '运行日志'}</button><button type="button" aria-pressed={tab === 'summary'} onClick={() => update({ detail: 'summary' })}><FileText size={15} />生成速递</button></div>
          {tab === 'logs' ? <Logs run={run} /> : tab === 'summary' ? <RunSummary run={run} query={query} update={update} /> : <StageItems run={run} stage={stage} query={query} update={update} />}
        </>}
      </section>
    </div>}
  </>
}

function StageItems({ run, stage, query, update }: { run: Run; stage: Stage; query: URLSearchParams; update: Update }) {
  const [term, setTerm] = useState(query.get('q') || '')
  const debounced = useDebounced(term)
  useEffect(() => setTerm(query.get('q') || ''), [query.get('q')])
  useEffect(() => { if (debounced !== (query.get('q') || '')) update({ q: debounced || null, offset: null }, true) }, [debounced])
  const params = new URLSearchParams({ limit: '30', offset: query.get('offset') || '0', q: query.get('q') || '', source: query.get('source') || '', disposition: query.get('disposition') || 'all', ...(stage !== 'raw' && query.get('min_score') ? { min_score: query.get('min_score')! } : {}) })
  const available = run.stages?.[stage]
  const resource = useResource<StageData>(available ? `/api/runs/${encodeURIComponent(run.run_id)}/stages/${stage}?${params}` : null, run.status === 'running' ? 5000 : 0)
  const d = resource.data
  const offset = Number(query.get('offset') || '0')
  if (!available) return <Empty title={run.status === 'running' ? '阶段工件尚未生成' : '没有这个阶段的工件'}>{run.status === 'running' ? '处理完成后会自动更新。你可以先查看实时日志。' : '该次运行可能跳过此阶段、提前结束，或来自旧版服务。已有工件仍可切换查看。'}</Empty>
  return <>
    <div className="item-filters"><label className="search-field"><Search size={16} /><span className="visually-hidden">搜索阶段条目</span><input type="search" value={term} onChange={e => setTerm(e.target.value)} placeholder="搜索标题、内容或评分原因" /></label><label><span className="visually-hidden">按信息源筛选</span><select aria-label="按信息源筛选" value={query.get('source') || ''} onChange={e => update({ source: e.target.value || null, offset: null })}><option value="">所有来源</option>{Object.keys(d?.source_counts || {}).map(s => <option key={s} value={s}>{sourceName(s)}</option>)}</select></label>{stage !== 'raw' && <select aria-label="最低评分" value={query.get('min_score') || ''} onChange={e => update({ min_score: e.target.value || null, offset: null })}><option value="">所有评分</option><option value="5">5 分及以上</option><option value="7">7 分及以上</option><option value="8">8 分及以上</option><option value="9">9 分及以上</option></select>}{['raw', 'scored'].includes(stage) && <select aria-label="按保留状态筛选" value={query.get('disposition') || 'all'} onChange={e => update({ disposition: e.target.value, offset: null })}><option value="all">全部条目</option><option value="kept">进入筛选结果</option><option value="removed">未进入筛选结果</option></select>}</div>
    {resource.error && <ErrorBox message={resource.error} retry={resource.reload} />}
    {resource.loading && !d ? <Skeleton rows={4} /> : d && <>
      {stage === 'scored' && Object.keys(d.score_distribution || {}).length > 0 && <div className="score-distribution" aria-label="评分分布">{Object.entries(d.score_distribution).map(([bucket, count]) => <div key={bucket}><span>{bucket === 'unscored' ? '未评分' : `${bucket} 分`}</span><div className="distribution-track"><span style={{ transform: `scaleX(${count / Math.max(1, ...Object.values(d.score_distribution))})` }} /></div><b>{count}</b></div>)}</div>}
      <div className="list-caption"><span>{stages.find(s => s.id === stage)?.hint}</span><span>共 {number(d.total)} 条结果</span></div>
      {d.items.length ? d.items.map((item, index) => <ItemRow key={item.id || index} item={item} />) : <Empty title="没有匹配的条目" action={<Button onClick={() => { setTerm(''); update({ q: null, source: null, disposition: null, min_score: null, offset: null }) }}>清除筛选</Button>}>试着更换关键词或放宽来源与保留状态条件。</Empty>}
      {d.total > 30 && <div className="pagination"><span>第 {Math.floor(offset / 30) + 1} / {Math.ceil(d.total / 30)} 页</span><Button disabled={offset <= 0} onClick={() => update({ offset: String(Math.max(0, offset - 30)) })}>上一页</Button><Button disabled={offset + 30 >= d.total} onClick={() => update({ offset: String(offset + 30) })}>下一页</Button></div>}
    </>}
  </>
}

function Logs({ run }: { run: Run }) {
  const [logs, setLogs] = useState<Log[]>([])
  const [error, setError] = useState('')
  const [connected, setConnected] = useState(false)
  const [follow, setFollow] = useState(true)
  const [term, setTerm] = useState('')
  const [level, setLevel] = useState('all')
  const viewport = useRef<HTMLDivElement>(null)
  useEffect(() => {
    setLogs([]); setError(''); setConnected(false)
    let disposed = false
    const merge = (items: Log[]) => setLogs(prev => [...new Map([...prev, ...items].map(l => [l.id, l])).values()].sort((a, b) => a.id - b.id).slice(-2000))
    void api<{ items: Log[] }>(`/api/runs/${encodeURIComponent(run.run_id)}/logs`).then(d => { if (!disposed) merge(d.items) }).catch(e => { if (!disposed) setError(e.message) })
    let stream: EventSource | undefined
    if (run.status === 'running') {
      stream = new EventSource(`/api/runs/${encodeURIComponent(run.run_id)}/logs/stream`)
      stream.onopen = () => { setConnected(true); setError('') }
      stream.addEventListener('log', event => { try { merge([JSON.parse((event as MessageEvent).data)]) } catch { setError('收到无法解析的日志，请刷新重试。') } })
      stream.onerror = () => setConnected(false)
      stream.addEventListener('done', () => { stream?.close(); setConnected(false) })
    }
    return () => { disposed = true; stream?.close() }
  }, [run.run_id, run.status])
  useEffect(() => { if (follow && viewport.current) viewport.current.scrollTop = viewport.current.scrollHeight }, [logs, follow])
  const filtered = logs.filter(l => (level === 'all' || l.level.toLowerCase() === level) && l.message.toLowerCase().includes(term.toLowerCase()))
  return <div className="logs-section"><div className="logs-toolbar"><div className="inline-meta"><Badge status={run.status === 'running' ? 'running' : 'unknown'}>{run.status === 'running' ? connected ? '实时连接' : '正在连接 / 重连' : '历史日志'}</Badge><span>最多显示最近 2,000 行</span></div><div className="inline-meta"><Button small onClick={() => setFollow(!follow)}>{follow ? <Pause size={14} /> : <Play size={14} />}{follow ? '暂停跟随' : '跟随最新'}</Button><button type="button" className="icon-button" aria-label="下载日志" onClick={() => download(`${run.run_id}.log`, logs.map(l => `${l.time} [${l.level}] ${l.message}`).join('\n'))}><Download size={17} /></button></div></div>
    <div className="log-filters"><label className="search-field"><Search size={15} /><input aria-label="搜索日志" type="search" placeholder="搜索日志" value={term} onChange={e => setTerm(e.target.value)} /></label><select aria-label="日志级别" value={level} onChange={e => setLevel(e.target.value)}><option value="all">全部级别</option><option value="info">信息</option><option value="warning">警告</option><option value="error">错误</option><option value="debug">调试</option></select></div>
    {error && <ErrorBox message={error} />}
    <div className="log-viewport" ref={viewport} tabIndex={0} aria-label="运行日志内容">{filtered.length ? filtered.map(l => <div className={`log-line ${l.level.toLowerCase()}`} key={l.id}><time>{l.time ? new Date(l.time).toLocaleTimeString('zh-CN', { hour12: false }) : ''}</time><span className="log-level">{l.level}</span><span>{l.message}</span></div>) : <p className="log-placeholder">{term || level !== 'all' ? '没有匹配的日志。' : '此运行暂无持久化日志。新运行的输出会在这里实时出现。'}</p>}</div>
  </div>
}

function RunSummary({ run, query, update }: { run: Run; query: URLSearchParams; update: Update }) {
  const language = query.get('language') || 'zh'
  const summary = useResource<{ markdown: string }>(`/api/runs/${encodeURIComponent(run.run_id)}/summary?language=${encodeURIComponent(language)}`, run.status === 'running' ? 6000 : 0)
  return <div className="run-summary"><div className="reading-toolbar"><label>速递语言<select value={language} onChange={e => update({ language: e.target.value })}><option value="zh">简体中文</option><option value="en">英语</option></select></label>{summary.data && <Button onClick={() => download(`${run.run_id}-${language}.md`, summary.data!.markdown, 'text/markdown;charset=utf-8')}><Download size={15} />下载 Markdown</Button>}</div>{summary.loading ? <Skeleton rows={5} /> : summary.error ? <Empty title="该语言的速递尚未生成">可切换语言，或等待流水线完成。请求结果：{summary.error}</Empty> : summary.data && <Markdown text={summary.data.markdown} />}</div>
}
