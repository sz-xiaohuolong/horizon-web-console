import { useEffect, useState } from 'react'
import { Check, Code2, LockKeyhole, Plus, RotateCcw, Save, Trash2 } from 'lucide-react'
import { Badge, Button, Empty, ErrorBox, Notice, PageTitle, SectionHead, Skeleton } from './components'
import { api, patchSource, sourceName } from './lib'
import { useDirtyGuard, useQuery, useResource } from './hooks'
import type { ConfigData, Json } from './types'

export function SettingsPage({ onDirty, onSaved }: { onDirty: (dirty: boolean) => void; onSaved: () => void }) {
  const resource = useResource<ConfigData>('/api/config')
  const [draft, setDraft] = useState<Json | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [jsonDirty, setJsonDirty] = useState(false)
  const { query, update } = useQuery()
  const tab = query.get('config') || 'sources'
  const selectTab = (next: string) => {
    if (next === tab) return
    if (jsonDirty && !window.confirm('高级 JSON 尚未应用，切换会丢弃这部分输入，是否继续？')) return
    setJsonDirty(false); update({ config: next })
  }
  useEffect(() => { if (resource.data) { setDraft(structuredClone(resource.data.config)); setJsonDirty(false) } }, [resource.data])
  const dirty = !!draft && !!resource.data && JSON.stringify(draft) !== JSON.stringify(resource.data.config) || jsonDirty
  useEffect(() => { onDirty(dirty); return () => onDirty(false) }, [dirty, onDirty])
  useDirtyGuard(dirty)
  const change = (key: string, value: unknown) => { setDraft(d => ({ ...d, [key]: value })); setMessage('') }
  const reset = () => {
    if (dirty && !window.confirm('放弃所有未保存的配置修改？')) return
    setDraft(resource.data ? structuredClone(resource.data.config) : null); setJsonDirty(false); setError(''); setMessage('')
  }
  const reload = () => { if (!dirty || window.confirm('重新加载会丢弃本地草稿，是否继续？')) { resource.reload(); setError(''); setJsonDirty(false) } }
  const save = async () => {
    if (!draft || !resource.data) return
    if (jsonDirty) { setError('高级 JSON 还有未应用的内容。请先应用到草稿，再保存配置。'); return }
    const patch: Json = {}
    for (const key of ['sources', 'processing', 'collection', 'digest', 'wechat']) {
      if (JSON.stringify(draft[key]) !== JSON.stringify(resource.data.config[key])) patch[key] = draft[key]
    }
    if (patch.sources) patch.sources = Object.fromEntries(Object.entries(draft.sources || {}).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(resource.data!.config.sources?.[key])))
    if (patch.processing) patch.processing = { default_profile: patch.processing.default_profile, profile_settings: patch.processing.profile_settings }
    setBusy(true); setError(''); setMessage('')
    try {
      const value = await api<ConfigData>('/api/config', { method: 'PATCH', body: JSON.stringify({ revision: resource.data.revision, patch }) })
      resource.setData(value); setDraft(structuredClone(value.config)); setMessage('配置已保存，并已在本机保留修改前的备份。下一次运行将使用新配置。'); onSaved()
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  return <><PageTitle title="配置工作区" description="调整信息源与筛选规则，配置保存后对下一次运行生效。" actions={<><Button onClick={reload}>重新加载</Button><Button primary disabled={!dirty || busy} onClick={save} aria-busy={busy}><Save size={16} />{busy ? '正在保存…' : '保存配置'}</Button></>} />
    {resource.error && <ErrorBox message={resource.error} retry={resource.reload} />}
    {error && <ErrorBox message={error} />}
    {message && <div className="notice success" role="status"><Check size={18} />{message}</div>}
    {dirty && <div className="draft-bar"><span>有未保存的修改</span><button type="button" className="text-button" onClick={reset}><RotateCcw size={14} />放弃修改</button></div>}
    {resource.loading || !draft ? !resource.error && <Skeleton rows={5} /> : <>
      <div className="view-tabs"><button type="button" aria-pressed={tab === 'sources'} onClick={() => selectTab('sources')}>信息源</button><button type="button" aria-pressed={tab === 'rules'} onClick={() => selectTab('rules')}>筛选规则</button><button type="button" aria-pressed={tab === 'system'} onClick={() => selectTab('system')}>服务配置</button></div>
      {tab === 'rules' ? <Rules config={draft} profiles={resource.data?.profiles || []} change={change} /> : tab === 'system' ? <System config={draft} change={change} /> : <Sources sources={draft.sources || {}} change={s => change('sources', s)} onJsonDirty={setJsonDirty} />}
    </>}
  </>
}

function Sources({ sources, change, onJsonDirty }: { sources: Json; change: (s: Json) => void; onJsonDirty: (dirty: boolean) => void }) {
  const keys = Object.keys(sources)
  const [kind, setKind] = useState('rss')
  const selected = keys.includes(kind) ? kind : keys[0]
  const source = sources[selected]
  const [advanced, setAdvanced] = useState(false)
  const [json, setJson] = useState('')
  const [jsonError, setJsonError] = useState('')
  const jsonChanged = advanced && json !== JSON.stringify(source, null, 2)
  useEffect(() => { setJson(JSON.stringify(source, null, 2)); setJsonError('') }, [selected, source])
  useEffect(() => { onJsonDirty(jsonChanged) }, [jsonChanged, onJsonDirty])
  const pick = (next: string) => {
    if (jsonChanged && !window.confirm('高级 JSON 尚未应用，切换会丢弃这部分输入，是否继续？')) return
    setKind(next); setAdvanced(false)
  }
  const setSource = (value: unknown) => change({ ...sources, [selected]: value })
  const add = () => {
    const template = selected === 'rss' ? { name: '新订阅', url: 'https://example.com/feed.xml', enabled: false, category: null, profile: null }
      : selected === 'github' ? { type: 'repo_releases', owner: '', repo: '', enabled: false, category: null, profile: null }
      : { enabled: false }
    setSource([...(Array.isArray(source) ? source : []), template])
  }
  const remove = (index: number) => setSource(source.filter((_: unknown, i: number) => i !== index))
  return <div className="settings-layout"><aside className="source-picker" aria-label="选择信息源类型">{keys.map(key => {
    const value = sources[key]
    const count = Array.isArray(value) ? value.length : value ? Object.values(value).filter(Array.isArray).reduce((sum: number, a) => sum + (a as unknown[]).length, 0) : 0
    const enabled = Array.isArray(value) ? value.some((s: Json) => s.enabled) : value?.enabled
    return <button type="button" key={key} className={key === selected ? 'selected' : ''} aria-pressed={key === selected} onClick={() => pick(key)}><span>{sourceName(key)}</span><span className={enabled ? 'source-enabled' : 'muted'}>{count ? `${count} 项` : enabled ? '已启用' : '未启用'}</span></button>
  })}</aside><section className="source-editor"><SectionHead title={sourceName(selected)} aside={<div className="inline-meta">{Array.isArray(source) && <Button onClick={add}><Plus size={15} />添加条目</Button>}<Button onClick={() => { if (advanced && jsonChanged && !window.confirm('关闭会丢弃尚未应用的 JSON 输入，是否继续？')) return; setAdvanced(!advanced); setJson(JSON.stringify(source, null, 2)) }}><Code2 size={15} />{advanced ? '返回表单' : '高级 JSON'}</Button></div>}>默认停用新条目。确认地址、分类和处理配置后再启用。</SectionHead>
    {advanced ? <div className="advanced-editor"><label>信息源 JSON<textarea aria-label="信息源 JSON" className="json-textarea" aria-describedby="source-json-help" spellCheck={false} value={json} onChange={e => { setJson(e.target.value); setJsonError('') }} /></label><p id="source-json-help" className="field-help">仅编辑当前信息源的结构。凭据由本地环境维护，脱敏占位符须保留。</p>{jsonError && <ErrorBox message={jsonError} />}<Button onClick={() => { try { const value = JSON.parse(json); if (typeof value !== 'object' || value === null) throw new Error(); setSource(value); setJsonError('') } catch { setJsonError('JSON 格式不正确，请检查括号、引号和逗号。') } }}>应用到草稿</Button></div>
      : Array.isArray(source) ? source.length ? <div className="source-entries">{source.map((entry: Json, index: number) => <div className="source-entry" key={index}><div className="source-entry-heading"><h3>{entry.name || (entry.owner && entry.repo ? `${entry.owner}/${entry.repo}` : entry.username) || `条目 ${index + 1}`}</h3><div className="inline-meta"><label className="switch-label"><input type="checkbox" checked={!!entry.enabled} onChange={e => change(patchSource(sources, selected, index, { enabled: e.target.checked }))} />启用</label><button type="button" className="icon-button danger" aria-label={`移除条目 ${index + 1}`} onClick={() => remove(index)}><Trash2 size={16} /></button></div></div><PrimitiveFields value={entry} change={patch => change(patchSource(sources, selected, index, patch))} /></div>)}</div> : <Empty title="还没有添加信息源" action={<Button onClick={add}><Plus size={15} />添加条目</Button>}>添加一个订阅或仓库后，启用它即可纳入下一次采集。</Empty>
      : source ? <><label className="check-label source-toggle"><input type="checkbox" checked={!!source.enabled} onChange={e => setSource({ ...source, enabled: e.target.checked })} />启用 {sourceName(selected)}</label><PrimitiveFields value={source} change={patch => setSource({ ...source, ...patch })} />{Object.entries(source).filter(([, value]) => Array.isArray(value) || typeof value === 'object' && value !== null).length > 0 && <Notice>该信息源包含频道、关键词或其他嵌套配置。使用“高级 JSON”可完整增删改；保存前会按原项目配置模型校验。</Notice>}</>
      : <Empty title="该信息源尚未配置" action={<Button onClick={() => { setAdvanced(true); setJson('{\n  "enabled": false\n}') }}>创建配置</Button>}>通过高级 JSON 填写该信息源的配置；首次保存前会验证所需字段。</Empty>}
  </section></div>
}
const fieldNames: Record<string, string> = {
  name: '名称', url: '订阅地址', owner: '仓库所有者', repo: '仓库名称', type: '采集类型', username: '用户名',
  category: '分类标签', profile: '处理配置', content_extractor: '正文提取器', fetch_top_stories: '采集数量',
  min_score: '最低热度', fetch_limit: '采集上限', fetch_comments: '评论数量', sort: '排序方式',
  time_window_hours: '独立采集时间窗（小时，留空沿用运行设置）', max_items: '单次采集上限',
  time_filter: '时间范围', language: '语言', country: '国家', max_results: '结果上限',
}
function PrimitiveFields({ value, change }: { value: Json; change: (patch: Json) => void }) {
  const fields = Object.entries(value).filter(([key, v]) => key !== 'enabled' && !/(token|secret|password|api_key|cookie|header)/i.test(key) && (v == null || ['string', 'number', 'boolean'].includes(typeof v)))
  return <div className="form-grid">{fields.map(([key, v]) => typeof v === 'boolean' ? <label className="check-label" key={key}><input type="checkbox" checked={v} onChange={e => change({ [key]: e.target.checked })} />{fieldNames[key] || key}</label> : <label key={key} className={key === 'url' ? 'wide-field' : ''}>{fieldNames[key] || key}{(typeof v === 'number' || ['time_window_hours', 'max_items'].includes(key)) ? <input type="number" value={v ?? ''} onChange={e => change({ [key]: e.target.value === '' ? null : Number(e.target.value) })} /> : key === 'type' && ['repo_releases', 'user_events'].includes(String(v)) ? <select value={v || ''} onChange={e => change({ [key]: e.target.value })}><option value="repo_releases">仓库发布</option><option value="user_events">用户动态</option></select> : <input type={key === 'url' ? 'url' : 'text'} value={v || ''} placeholder={key === 'profile' ? '留空由 AI 自动匹配' : key === 'url' ? 'https://example.com/feed.xml' : undefined} onChange={e => change({ [key]: e.target.value || (v == null ? null : '') })} />}</label>)}</div>
}

function Rules({ config, profiles, change }: { config: Json; profiles: ConfigData['profiles']; change: (key: string, value: unknown) => void }) {
  const settings = config.processing?.profile_settings || {}
  const updateProfile = (id: string, patch: Json) => change('processing', { ...config.processing, profile_settings: { ...settings, [id]: { ...settings[id], ...patch } } })
  const groups = config.digest?.category_groups || {}
  const [newId, setNewId] = useState('')
  const [groupError, setGroupError] = useState('')
  return <div className="rules-layout"><section><SectionHead title="采集与筛选" /><div className="form-grid"><label>默认采集时间窗（小时）<input type="number" min="1" max="168" value={config.collection?.time_window_hours ?? 24} onChange={e => change('collection', { ...config.collection, time_window_hours: Number(e.target.value) })} /></label><label>默认处理配置<select value={config.processing?.default_profile || ''} onChange={e => change('processing', { ...config.processing, default_profile: e.target.value })}>{profiles.map(p => <option key={p.id} value={p.id}>{p.name || p.id}</option>)}</select></label></div>
    <div className="profile-rules">{profiles.map(p => {
      const value = settings[p.id] || {}
      return <div className="profile-rule" key={p.id}><div className="profile-title"><h3>{p.name || p.id}</h3><span>{p.id}</span></div><label className="check-label"><input type="checkbox" checked={value.threshold != null} onChange={e => updateProfile(p.id, { threshold: e.target.checked ? 7 : null })} />自定义评分阈值</label>{value.threshold != null ? <label className="range-field">最低评分 <output>{Number(value.threshold).toFixed(1)} / 10</output><input aria-label={`${p.name || p.id}最低评分`} type="range" min="0" max="10" step="0.5" value={value.threshold} onChange={e => updateProfile(p.id, { threshold: Number(e.target.value) })} /></label> : <p className="field-help">不按评分过滤；仍执行去重和速递配额。</p>}<label>最低保留条数<input aria-label={`${p.name || p.id}最低保留条数`} type="number" min="0" step="1" value={config.digest?.profile_min_items?.[p.id] ?? 0} onChange={e => change('digest', { ...config.digest, profile_min_items: { ...config.digest?.profile_min_items, [p.id]: Number(e.target.value) } })} /></label><p className="field-help">先保留达到评分门槛的内容；不足时记录缺口，分类上限仍然有效。0 表示不预留。</p><label className="check-label"><input type="checkbox" checked={value.topic_dedup ?? true} onChange={e => updateProfile(p.id, { topic_dedup: e.target.checked })} />启用主题去重</label></div>
    })}</div></section><section><SectionHead title="速递配额" /><div className="form-grid"><label>速递条目上限<input type="number" min="1" value={config.digest?.max_items ?? ''} placeholder="留空不限制" onChange={e => change('digest', { ...config.digest, max_items: e.target.value ? Number(e.target.value) : null })} /></label><label>其他分类上限<input type="number" min="1" value={config.digest?.default_group_limit ?? ''} placeholder="留空不限制" onChange={e => change('digest', { ...config.digest, default_group_limit: e.target.value ? Number(e.target.value) : null })} /></label></div>
      {Object.entries(groups).map(([id, group]) => { const g = group as Json; const set = (patch: Json) => change('digest', { ...config.digest, category_groups: { ...groups, [id]: { ...g, ...patch } } }); return <div className="quota-row" key={id}><div className="source-entry-heading"><h3>{g.name || id}</h3><button type="button" className="icon-button danger" aria-label={`移除配额组 ${id}`} onClick={() => { const next = { ...groups }; delete next[id]; change('digest', { ...config.digest, category_groups: next }) }}><Trash2 size={15} /></button></div><div className="form-grid"><label>显示名称<input value={g.name || ''} onChange={e => set({ name: e.target.value })} /></label><label>保留条数<input type="number" min="1" value={g.limit} onChange={e => set({ limit: Number(e.target.value) })} /></label><label className="wide-field">分类标签（英文逗号分隔）<input value={g.categories?.join(', ') || ''} onChange={e => set({ categories: e.target.value.split(',').map(s => s.trim()) })} /></label></div></div> })}
      <div className="add-group"><label>新增配额组标识<input value={newId} onChange={e => setNewId(e.target.value)} placeholder="例如 research" /></label><Button onClick={() => { if (!/^[a-zA-Z0-9_-]+$/.test(newId) || groups[newId]) { setGroupError('请输入未使用的英文、数字或下划线标识。'); return } change('digest', { ...config.digest, category_groups: { ...groups, [newId]: { name: newId, limit: 3, categories: [newId] } } }); setNewId(''); setGroupError('') }}><Plus size={15} />添加分组</Button></div>{groupError && <ErrorBox message={groupError} />}
    </section></div>
}

function System({ config, change }: { config: Json; change: (key: string, value: unknown) => void }) {
  return <div className="system-settings"><SectionHead title="AI 服务" aside={<Badge><LockKeyhole size={12} />仅本地文件可修改</Badge>}>凭据通过本地配置和环境变量管理，网页不会回显或写入密钥。</SectionHead><dl className="config-readonly"><div><dt>服务提供方</dt><dd>{config.ai?.provider || '未配置'}</dd></div><div><dt>模型</dt><dd>{config.ai?.model || '未配置'}</dd></div><div><dt>生成语言</dt><dd>{config.ai?.languages?.join('、') || '未配置'}</dd></div><div><dt>接口地址</dt><dd>{config.ai?.base_url || '使用服务默认值'}</dd></div></dl><section className="wechat-setting"><SectionHead title="微信推送开关" /><label className="check-label"><input type="checkbox" checked={!!config.wechat?.enabled} onChange={e => change('wechat', { ...config.wechat, enabled: e.target.checked })} />启用微信推送</label><p className="field-help">控制台运行只生成速递；生成后可在历史速递页手动确认推送。此开关也供 CLI 使用，扫码连接请前往微信连接页。</p></section></div>
}
