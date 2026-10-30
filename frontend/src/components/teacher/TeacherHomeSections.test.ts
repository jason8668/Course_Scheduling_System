import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { NMessageProvider } from 'naive-ui'
import { describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import TeacherHomeSections from './TeacherHomeSections.vue'

// 2026-10-30 再定后,仪表板教师个人节只剩提醒设置 + 行政值日:
// 通知改成右上角小框、请假/代课/调课都搬到调课管理页,这里不再验它们。
describe('TeacherHomeSections', () => {
  it('只列提醒设置,普通老师看不到行政值日节', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) =>
      Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(
        url.includes('reminder-preference') ? null
        : url.includes('/duty-roster') ? { patterns: [], overrides: [], swap_requests: [], eligible: [] }
        : [],
      ) })))
    const wrapper = mount(NMessageProvider, {
      global: { plugins: [createPinia()] },
      slots: { default: () => h(TeacherHomeSections, { semesterId: 1, teacherId: 99 }) },
    })
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('提醒设置')
    expect(text).not.toContain('我的请假')
    expect(text).not.toContain('我的代课')
    // teacherId 99 不在 eligible 里,值日节应隐藏
    expect(text).not.toContain('行政值日')
  })
})
