import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import NotificationWidget from './NotificationWidget.vue'

describe('NotificationWidget', () => {
  it('小框显示最新通知标题与未读数', async () => {
    vi.stubGlobal('fetch', vi.fn(() =>
      Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({
        items: [
          { id: 1, title: '张老师代你的课', body: '周三第2节', created_at: '2026-10-30 08:00', read_at: null, acknowledged_at: null },
        ], unread: 1,
      }) })))
    const wrapper = mount(NotificationWidget, { props: { semesterId: 1 } })
    await flushPromises()
    expect(wrapper.text()).toContain('通知')
    expect(wrapper.text()).toContain('1 条未读')
    expect(wrapper.text()).toContain('张老师代你的课')
  })
})
