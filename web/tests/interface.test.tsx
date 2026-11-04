// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import App from '../src/App'
import { SettingsPage } from '../src/Settings'
import { RunsPage } from '../src/Runs'
import { SummariesPage } from '../src/Reading'
import { Markdown } from '../src/components'

const config = { sources: { rss: [{ name: '本地验收订阅', url: 'https://example.org/feed', enabled: true }], telegram: { enabled: false, channels: [], token: '<redacted>' } }, processing: { default_profile: 'tech-news', profile_settings: {} }, collection: { time_window_hours: 24 }, digest: { category_groups: {} }, ai: {}, wechat: {} }
const active = { run_id: 'local-run', status: 'running', current_stage: 'raw', counts: {}, stages: {}, stage_durations: {}, created_at: '2026-11-04T00:00:00Z', tokens: null, duration_seconds: null }
beforeEach(() => {
  window.history.replaceState({}, '', '/?view=settings')
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'PATCH') return new Response(JSON.stringify({ detail: '配置已变化，请重新加载后再保存。' }), { status: 409 })
    const value = url === '/api/config' ? { revision: '1', config, profiles: [] } : url === '/api/overview' ? { active_run: active, busy: true, sources: [], ai: {}, wechat: {}, scheduler: {}, warnings: [] } : { items: [] }
    return new Response(JSON.stringify(value))
  }))
  vi.spyOn(window, 'confirm').mockReturnValue(false)
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('刷新归档会读取同一天被覆盖的报告正文', async () => {
  let text = '# 同日报告\n\n先前版本'
  vi.mocked(fetch).mockImplementation(async url => {
    const value = String(url) === '/api/summaries'
      ? { items: [{ id: 'horizon-2026-11-04-zh.md', date: '2026-11-04', language: 'zh', title: '同日报告', revision: text }], count: 1 }
      : { id: 'horizon-2026-11-04-zh.md', date: '2026-11-04', language: 'zh', markdown: text }
    return new Response(JSON.stringify(value))
  })
  render(<SummariesPage query={new URLSearchParams()} update={() => {}} />)
  await screen.findByText('先前版本')
  text = '# 同日报告\n\n刚生成的新报告'
  fireEvent.click(screen.getByRole('button', { name: '刷新归档' }))
  await screen.findByText('刚生成的新报告')
  expect(screen.queryByText('先前版本')).toBeNull()
})

describe('配置草稿与内容安全', () => {
  it('最低保留数保存到速递规则并保留其他配置', async () => {
    vi.mocked(fetch).mockImplementation(async (_url, init) => {
      if (init?.method === 'PATCH') return new Response(JSON.stringify({ detail: '保留草稿' }), { status: 409 })
      return new Response(JSON.stringify({ revision: '1', config, profiles: [{ id: 'tech-blog', name: '科技博客', threshold: null, topic_dedup: false }] }))
    })
    render(<SettingsPage onDirty={() => {}} onSaved={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: '筛选规则' }))
    fireEvent.change(screen.getByLabelText('科技博客最低保留条数'), { target: { value: '2' } })
    fireEvent.click(screen.getByRole('button', { name: '保存配置' }))
    await screen.findByRole('alert')
    const call = vi.mocked(fetch).mock.calls.find(([, init]) => init?.method === 'PATCH')!
    expect(JSON.parse(String(call[1]?.body)).patch).toEqual({ digest: { category_groups: {}, profile_min_items: { 'tech-blog': 2 } } })
  })
  it('高级 JSON 未应用时拒绝切页，原输入仍可恢复', async () => {
    render(<SettingsPage onDirty={() => {}} onSaved={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: '高级 JSON' }))
    fireEvent.change(screen.getByLabelText('信息源 JSON'), { target: { value: '[{"name":"尚未应用的输入"}]' } })
    fireEvent.click(screen.getByRole('button', { name: '筛选规则' }))
    expect(window.confirm).toHaveBeenCalled()
    expect((screen.getByLabelText('信息源 JSON') as HTMLTextAreaElement).value).toContain('尚未应用的输入')
    expect(window.location.search).not.toContain('rules')
  })
  it('确认放弃高级 JSON 后，其他配置页仍能正常保存草稿', async () => {
    vi.mocked(window.confirm).mockReturnValue(true)
    render(<SettingsPage onDirty={() => {}} onSaved={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: '高级 JSON' }))
    fireEvent.change(screen.getByLabelText('信息源 JSON'), { target: { value: '不完整的 JSON' } })
    fireEvent.click(screen.getByRole('button', { name: '筛选规则' }))
    fireEvent.change(screen.getByLabelText('默认采集时间窗（小时）'), { target: { value: '12' } })
    fireEvent.click(screen.getByRole('button', { name: '保存配置' }))
    await screen.findByRole('alert')
    expect(screen.getByRole('alert').textContent).toContain('配置已变化')
    expect((screen.getByLabelText('默认采集时间窗（小时）') as HTMLInputElement).value).toBe('12')
  })
  it('页头查看运行也保护尚未保存的配置', async () => {
    render(<App />)
    fireEvent.change(await screen.findByLabelText('名称'), { target: { value: '未保存的新名称' } })
    await waitFor(() => expect(screen.getByText('有未保存的修改')).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: /^查看运行$/ }))
    expect(window.confirm).toHaveBeenCalled()
    expect(window.location.search).toContain('settings')
    expect((screen.getByLabelText('名称') as HTMLInputElement).value).toBe('未保存的新名称')
  })
  it('保存冲突保留表单且发送 revision 与局部配置', async () => {
    render(<SettingsPage onDirty={() => {}} onSaved={() => {}} />)
    fireEvent.change(await screen.findByLabelText('名称'), { target: { value: '保留这个草稿' } })
    fireEvent.click(screen.getByRole('button', { name: '保存配置' }))
    await screen.findByRole('alert')
    expect((screen.getByLabelText('名称') as HTMLInputElement).value).toBe('保留这个草稿')
    const call = vi.mocked(fetch).mock.calls.find(([, init]) => init?.method === 'PATCH')!
    expect(JSON.parse(String(call[1]?.body))).toEqual({ revision: '1', patch: { sources: { rss: [{ name: '保留这个草稿', url: 'https://example.org/feed', enabled: true }] } } })
    expect((call[1]?.headers as Record<string, string>)['X-Horizon-Request']).toBe('1')
  })
  it('速递不执行 HTML，不加载远程图片，不开放危险链接', () => {
    const { container } = render(<Markdown text={'<script>alert(1)</script>\n\n[危险链接](javascript:alert%281%29)\n\n![远程图](https://example.org/tracker.png)\n\n[原文](https://example.org/news)'} />)
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('a[href^="javascript"]')).toBeNull()
    expect(container.querySelector('a')?.getAttribute('rel')).toBe('noreferrer')
    expect(container.textContent).toContain('[图片：远程图]')
  })
  it('原始采集阶段不继承已隐藏的最低评分过滤', async () => {
    vi.mocked(fetch).mockImplementation(async (url) => {
      const path = String(url)
      return new Response(JSON.stringify(path.startsWith('/api/runs?') ? { items: [active], count: 1 } : path.includes('/stages/') ? { items: [], total: 0 } : { ...active, stages: { raw: true } }))
    })
    render(<RunsPage query={new URLSearchParams('run=local-run&stage=raw&min_score=9')} update={() => {}} onChanged={() => {}} openRun={() => {}} />)
    await screen.findByText('没有匹配的条目')
    const call = vi.mocked(fetch).mock.calls.find(([url]) => String(url).includes('/stages/raw'))!
    expect(String(call[0])).not.toContain('min_score')
  })
})

it('微信预览和取消不发送消息，确认后才发送当前版本', async () => {
  const report = { id: 'horizon-2026-11-04-zh.md', date: '2026-11-04', language: 'zh', title: '微信测试报告', revision: 'report-v1', markdown: '# 微信测试报告\n\n正文' }
  vi.mocked(fetch).mockImplementation(async (url, init) => {
    const path = String(url)
    const value = path === '/api/summaries' ? { items: [report], count: 1 }
      : path.endsWith('/wechat') ? init?.method === 'POST'
        ? { status: 'success', chunks_sent: 2, message: '已推送到微信，共 2 段。' }
        : { revision: report.revision, confirmation: 'confirm-v1', chunk_count: 2, remaining_budget: 10, can_send: true }
      : report
    return new Response(JSON.stringify(value))
  })
  render(<SummariesPage query={new URLSearchParams()} update={() => {}} />)
  fireEvent.click(await screen.findByRole('button', { name: '推送到微信' }))
  await screen.findByRole('button', { name: '确认发送 2 段' })
  expect(vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: '取消推送' }))
  expect(screen.queryByRole('button', { name: '确认发送 2 段' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '推送到微信' }))
  fireEvent.click(await screen.findByRole('button', { name: '确认发送 2 段' }))
  await screen.findByText('已推送到微信，共 2 段。')
  const posts = vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === 'POST')
  expect(posts).toHaveLength(1)
  expect(JSON.parse(String(posts[0][1]?.body))).toEqual({ revision: 'report-v1', confirmation: 'confirm-v1' })
})
