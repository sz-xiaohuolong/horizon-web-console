import { useState } from 'react'
import { Activity, ArrowRight, BookOpen, Check, ChevronRight, CircleHelp, History, Play, Radio, RefreshCw, Settings2, X } from 'lucide-react'
import { api, dateTime } from './lib'
import { useQuery, useResource } from './hooks'
import { Button, ErrorBox } from './components'
import { OverviewPage } from './Overview'
import { RunsPage } from './Runs'
import { SettingsPage } from './Settings'
import { SummariesPage, WechatPage } from './Reading'
import type { Overview, Run } from './types'

const nav = [
  { id: 'overview', label: '观测台', icon: Activity }, { id: 'runs', label: '运行记录', icon: History },
  { id: 'summaries', label: '历史速递', icon: BookOpen }, { id: 'settings', label: '配置', icon: Settings2 },
  { id: 'wechat', label: '微信连接', icon: Radio },
]
export default function App() {
  const { query, update } = useQuery()
  const view = nav.some(v => v.id === query.get('view')) ? query.get('view')! : 'overview'
  const overview = useResource<Overview>('/api/overview', 8000)
  const [composer, setComposer] = useState(false)
  const [hours, setHours] = useState('24')
  const [enrich, setEnrich] = useState(true)
  const [language, setLanguage] = useState('default')
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')
  const [dirty, setDirty] = useState(false)
  const [help, setHelp] = useState(false)
  const navigate = (next: string) => {
    if (dirty && next !== view && !window.confirm('配置尚未保存。离开会丢弃本次修改，是否继续？')) return
    setDirty(false); update({ view: next, run: null, stage: null, q: null, source: null, disposition: null, min_score: null, offset: null, summary: null, language: null })
  }
  const showRun = (run: Run, stage?: string) => { setDirty(false); update({ view: 'runs', run: run.run_id, stage: stage || 'raw', offset: null, q: null, source: null, disposition: null, min_score: null, detail: null }) }
  const selectRun = (run: Run, stage?: string) => {
    if (dirty && !window.confirm('配置尚未保存。查看运行会丢弃本次修改，是否继续？')) return
    showRun(run, stage)
  }
  const start = async () => {
    if (dirty && !window.confirm('当前配置草稿尚未保存，将使用上次已保存的配置运行。是否继续？')) return
    setStarting(true); setError('')
    try {
      const run = await api<Run>('/api/runs', { method: 'POST', body: JSON.stringify({ hours: Number(hours), enrich, ...(language === 'default' ? {} : { languages: [language] }) }) })
      setComposer(false); showRun(run); overview.reload()
    } catch (e) { setError((e as Error).message) }
    finally { setStarting(false) }
  }
  const active = overview.data?.active_run
  const busy = !!active || overview.data?.busy
  return <>
    <a className="skip-link" href="#main">跳至主要内容</a>
    <header className="app-header"><div className="header-inner">
      <a href="?view=overview" className="wordmark" aria-label="Horizon 观测台首页" onClick={e => { e.preventDefault(); navigate('overview') }}><span className="horizon-mark"><Radio size={22} /></span>Horizon<span className="local-label">本地控制台</span></a>
      <nav aria-label="主要导航">{nav.map(({ id, label, icon: Icon }) => <a key={id} href={`?view=${id}`} aria-current={view === id ? 'page' : undefined} onClick={e => { e.preventDefault(); navigate(id) }}><Icon size={16} />{label}</a>)}</nav>
      <button type="button" className="icon-button help-button" onClick={() => setHelp(!help)} aria-label="使用帮助" aria-expanded={help}><CircleHelp size={19} /></button>
    </div></header>
    {help && <div className="help-panel container"><div><h2>从一次运行开始</h2><p>观测台查看全局状态，运行记录检查阶段和日志，历史速递阅读已生成的报告。配置修改保存后对下一次运行生效。所有时间按浏览器本地时区显示。</p><p>旧 CLI 任务没有阶段工件时，不会出现在运行记录中；原有速递仍可阅读。外部定时器不由本控制台管理。</p></div><Button onClick={() => setHelp(false)}>知道了<Check size={15} /></Button></div>}
    <main id="main" className="container app-main">
      <div className="workspace-bar"><div className="workspace-path"><span>个人工作区</span><ChevronRight size={14} /><span>{nav.find(n => n.id === view)?.label}</span></div><div className="workspace-actions"><span className="server-label">{overview.error ? '连接异常' : '本机服务'}</span><button type="button" className="icon-button" aria-label="刷新全局状态" onClick={overview.reload}><RefreshCw size={15} /></button><Button primary onClick={() => busy && active ? selectRun(active) : setComposer(!composer)} disabled={starting || (busy && !active)}>{active ? <Activity size={16} /> : <Play size={15} />}{active ? '查看运行' : busy ? '工作区使用中' : '运行一次'}</Button></div></div>
      {composer && <section className="run-composer" aria-label="发起流水线运行"><div className="section-heading"><div><h2>运行流水线</h2><p>使用已保存的配置访问外部信息源和 AI 服务，可能产生模型费用；只生成速递。</p></div><button type="button" className="icon-button" aria-label="关闭运行表单" onClick={() => setComposer(false)}><X size={18} /></button></div><div className="run-fields">
        <label>采集时间范围<select value={hours} onChange={e => setHours(e.target.value)}><option value="12">最近 12 小时</option><option value="24">最近 24 小时</option><option value="48">最近 48 小时</option><option value="72">最近 72 小时</option><option value="168">最近 7 天</option></select></label>
        <label>速递语言<select value={language} onChange={e => setLanguage(e.target.value)}><option value="default">使用配置语言</option><option value="zh">简体中文</option><option value="en">英语</option></select></label>
        <label className="check-label"><input type="checkbox" checked={enrich} onChange={e => setEnrich(e.target.checked)} />启用深度补充</label>
        <Button primary onClick={start} disabled={starting} aria-busy={starting}>{starting ? '正在启动…' : '开始运行'}<ArrowRight size={16} /></Button>
      </div>{error && <ErrorBox message={error} />}</section>}
      {overview.error && view !== 'overview' && <ErrorBox message={overview.error} retry={overview.reload} />}
      {view === 'overview' && <OverviewPage resource={overview} selectRun={selectRun} navigate={navigate} openRun={() => setComposer(true)} />}
      {view === 'runs' && <RunsPage query={query} update={update} onChanged={overview.reload} openRun={() => setComposer(true)} />}
      {view === 'summaries' && <SummariesPage query={query} update={update} />}
      {view === 'settings' && <SettingsPage onDirty={setDirty} onSaved={overview.reload} />}
      {view === 'wechat' && <WechatPage onChanged={overview.reload} />}
    </main>
    <footer className="app-footer container"><span>Horizon<span>信息流的每一步，都有迹可循。</span></span><span>{active ? `运行开始于 ${dateTime(active.created_at, true)}` : '数据保存在本机'}<a href="/api/docs" target="_blank" rel="noreferrer">API 文档</a></span></footer>
  </>
}
