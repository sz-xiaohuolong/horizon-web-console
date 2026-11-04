import { ArrowUpRight, BookOpen, Check, Cpu, Radio, Timer } from 'lucide-react'
import { Badge, Button, Empty, ErrorBox, Notice, PageTitle, Pipeline, RunTable, SectionHead, Skeleton } from './components'
import { dateTime, duration, number, sourceName } from './lib'
import { useResource } from './hooks'
import type { Overview, Run, Stage, Summary } from './types'

export function OverviewPage({ resource, selectRun, navigate, openRun }: {
  resource: { data: Overview | null; loading: boolean; error: string; reload: () => void }
  selectRun: (run: Run, stage?: Stage) => void; navigate: (view: string) => void; openRun: () => void
}) {
  const runs = useResource<{ items: Run[]; count: number }>('/api/runs?limit=5', 8000)
  const summaries = useResource<{ items: Summary[]; count: number }>('/api/summaries')
  const data = resource.data
  const latest = data?.active_run || data?.latest_run || null
  return <>
    <PageTitle title="信息流，一目了然" description="从原始信息到值得阅读的速递，观察每一步。" />
    {resource.error && <ErrorBox message={resource.error} retry={resource.reload} />}
    {resource.loading && !data ? <Skeleton rows={4} /> : data && <>
      {!!data.warnings?.length && <Notice>{data.warnings.join('；')}</Notice>}
      <section className="pipeline-panel"><SectionHead title={data.active_run ? '正在运行的流水线' : '最近一次流水线'} aside={latest ? <div className="inline-meta"><span>{dateTime(latest.created_at, true)}</span><Badge status={latest.status} /></div> : <Badge>等待首次运行</Badge>} />
        <Pipeline run={latest} onSelect={stage => latest && selectRun(latest, stage)} />
        <div className="pipeline-bottom">{latest ? <><span className="muted">运行编号 <span className="measured">{latest.run_id}</span></span><button type="button" className="text-button" onClick={() => selectRun(latest)}>检查阶段与日志<ArrowUpRight size={15} /></button></> : <><span>Web 运行会保存阶段工件，方便回溯评分和筛选。</span><button type="button" className="text-button" onClick={openRun}>发起首次运行<ArrowUpRight size={15} /></button></>}</div>
      </section>
      <dl className="readings"><div><dt>累计运行</dt><dd>{number(data.run_count)}<span>次</span></dd></div><div><dt>历史速递</dt><dd>{number(data.summary_count)}<span>份</span></dd></div><div><dt>最近运行耗时</dt><dd className="reading-text">{duration(latest?.duration_seconds)}</dd></div><div><dt>最近 Token 用量</dt><dd>{number(latest?.tokens?.total)}<span>tokens</span></dd></div></dl>
      <div className="overview-columns"><div className="overview-main"><section><SectionHead title="最近运行" aside={<button type="button" className="text-button" onClick={() => navigate('runs')}>全部运行<ArrowUpRight size={15} /></button>} />
        {runs.error ? <ErrorBox message={runs.error} retry={runs.reload} /> : runs.loading ? <Skeleton /> : <RunTable runs={runs.data?.items || []} select={selectRun} />}
      </section><section className="digest-preview"><SectionHead title="已生成的速递" aside={<button type="button" className="text-button" onClick={() => navigate('summaries')}>打开归档<ArrowUpRight size={15} /></button>} />
        {summaries.error ? <ErrorBox message={summaries.error} retry={summaries.reload} /> : summaries.loading ? <Skeleton rows={2} /> : summaries.data?.items.length ? <div className="summary-preview-list">{summaries.data.items.slice(0, 3).map(s => <button type="button" key={s.id} onClick={() => navigate('summaries')}><BookOpen size={18} /><span><strong>{s.title || `${s.date} 每日速递`}</strong><small>{s.date} <span>{s.language === 'zh' ? '简体中文' : s.language === 'en' ? '英语' : s.language}</span></small></span><ArrowUpRight size={16} /></button>)}</div> : <Empty title="速递归档还是空的">流水线完成后，生成的 Markdown 报告会出现在这里。</Empty>}
      </section></div>
      <aside className="system-aside"><SectionHead title="工作区状态" /><dl className="system-list"><div><dt><Cpu size={16} />AI 服务</dt><dd><span>{data.ai?.provider || '未配置'}</span><small className="measured">{data.ai?.model || '请检查配置'}</small></dd></div><div><dt><Radio size={16} />微信连接</dt><dd><Badge status={data.wechat?.ready ? 'ready' : 'unknown'}>{data.wechat?.ready ? '可接收推送' : data.wechat?.connected ? '等待首条消息' : '未连接'}</Badge><button type="button" className="text-button" onClick={() => navigate('wechat')}>管理连接</button></dd></div><div><dt><Timer size={16} />定时任务</dt><dd><span>外部调度</span><small>{data.scheduler?.message || '控制台未接管定时任务。'}</small></dd></div></dl>
        <div className="source-heading"><h3>信息源</h3><span>{data.sources.filter(s => s.enabled).length} 种已启用</span></div><ul className="source-list">{data.sources.map(s => <li key={s.id}><span>{sourceName(s.id)}</span><span className={s.enabled ? 'source-enabled' : 'muted'}>{s.enabled ? <><Check size={13} />已启用</> : '已停用'}</span></li>)}</ul><Button onClick={() => navigate('settings')}>管理信息源<ArrowUpRight size={14} /></Button>
      </aside></div>
    </>}
  </>
}
