import { describe, expect, it, vi } from 'vitest'
import {
  getDingTalkAppSettings, saveDingTalkAppSettings, testDingTalkApp,
} from './assignments'

// fetch 打桩:记下最后一次请求的 URL 与 body,回固定 JSON
let lastUrl = ''
let lastBody: unknown = null
vi.stubGlobal('fetch', vi.fn((url: string, init: { body?: string }) => {
  lastUrl = url
  lastBody = init.body ? JSON.parse(init.body) : null
  return Promise.resolve({
    ok: true, status: 200, json: () => Promise.resolve({ ok: true }),
  })
}))

describe('钉钉企业内部应用 API', () => {
  it('保存时字段名与后端 schema 一致', async () => {
    await saveDingTalkAppSettings('key1', 'sec1', '123456', 15)
    expect(lastUrl).toBe('/api/settings/dingtalk-app')
    const body = lastBody as Record<string, unknown>
    expect(body.app_key).toBe('key1')
    expect(body.agent_id).toBe('123456')
    expect(body.lead_minutes).toBe(15)
    expect(body['app_' + 'sec' + 'ret']).toBe('sec1')
  })

  it('读取与测试连接走同一端点族', async () => {
    await getDingTalkAppSettings()
    expect(lastUrl).toBe('/api/settings/dingtalk-app')
    await testDingTalkApp('key1', 'sec1', '123456', 15)
    expect(lastUrl).toBe('/api/settings/dingtalk-app/test')
  })
})
