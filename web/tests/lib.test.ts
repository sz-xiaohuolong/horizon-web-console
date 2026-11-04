import { describe, it, expect } from 'vitest'
import { duration, number, safeUrl, sourceName, itemAnalysis, patchSource, formatApiError } from '../src/lib'

describe('观测值与安全边界', () => {
  it('区分缺失指标与真实零值', () => {
    expect(number(null)).toBe('—')
    expect(number(0)).toBe('0')
    expect(duration(null)).toBe('未记录')
    expect(duration(65)).toBe('1 分 5 秒')
  })
  it('拒绝摘要及条目中的非网页协议', () => {
    expect(safeUrl('javascript:alert(1)')).toBeUndefined()
    expect(safeUrl('data:text/html,test')).toBeUndefined()
    expect(safeUrl('https://example.com/news')).toBe('https://example.com/news')
  })
  it('从真实processing结构读取评分和中文来源', () => {
    expect(itemAnalysis({ processing: { analysis: { score: 0, reason: '缺少来源' } } }).score).toBe(0)
    expect(sourceName('google_news')).toBe('Google 新闻')
  })
  it('信息源启停保留原有字段且不修改原对象', () => {
    const sources = { rss: [{ name: '研究', url: 'https://example.com/feed', enabled: true }] }
    const result = patchSource(sources, 'rss', 0, { enabled: false })
    expect(result.rss[0]).toEqual({ name: '研究', url: 'https://example.com/feed', enabled: false })
    expect(sources.rss[0].enabled).toBe(true)
  })
  it('验证错误不会把内部输入或对象直接显示为错误文本', () => {
    expect(formatApiError({detail:[{loc:['body','hours'],msg:'Input should be less than or equal to 168',input:'secret'}]},422)).not.toContain('secret')
    expect(formatApiError({detail:'配置已变化，请刷新后重试'},409)).toContain('配置已变化')
  })
})
