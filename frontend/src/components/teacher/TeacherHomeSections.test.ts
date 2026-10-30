import { flushPromises, mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import TeacherHomeSections from './TeacherHomeSections.vue'

// 原「我的」页搬进仪表板的部分:通知、请假、代课、提醒设置、值日、调课,
// 本周课表不搬(仪表板已有一张更好的),故这里只验搬过来的节在不在。
describe('TeacherHomeSections', () => {
  it('列出通知、请假、代课、提醒设置四节', async () => {
    // 按接口分流:通知回 {items}，代课统计回 {summaries, details}，
    // 值日回 {patterns, overrides, swap_requests, eligible}，其余列表回数组。
    vi.stubGlobal('fetch', vi.fn((url: string) =>
      Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(
        url.includes('/notifications/mine') ? { items: [], unread: 0 }
        : url.includes('reminder-preference') ? null
        : url.includes('substitution-stats') ? { summaries: [], details: [] }
        : url.includes('/duty-roster') ? { patterns: [], overrides: [], swap_requests: [], eligible: [] }
        : [],
      ) })))
    const wrapper = mount(NMessageProvider, {
      slots: { default: () => h(TeacherHomeSections, { semesterId: 1 }) },
    })
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('通知')
    expect(text).toContain('我的请假')
    expect(text).toContain('我的代课')
    expect(text).toContain('提醒设置')
  })
})
