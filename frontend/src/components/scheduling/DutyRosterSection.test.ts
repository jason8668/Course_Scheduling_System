import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { NMessageProvider } from 'naive-ui'
import { describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import DutyRosterSection from './DutyRosterSection.vue'

// 值日管理段只做两件事:把轮值与换班申请列出来,管理员改轮值时只给行政岗老师选。
const roster = {
  patterns: [{ id: 1, weekday: 1, teacher_id: 1, teacher_name: '张主任' }],
  overrides: [],
  swap_requests: [{
    id: 1, date: '2026-11-02', from_teacher_id: 1, from_teacher_name: '张主任',
    to_teacher_id: 2, to_teacher_name: '李副主任', status: 'pending',
  }],
  eligible: [
    { id: 1, name: '张主任', admin_title: '教务主任' },
    { id: 2, name: '李副主任', admin_title: '副主任' },
  ],
}

describe('DutyRosterSection', () => {
  it('管理员模式列出轮值与换班申请', async () => {
    vi.stubGlobal('fetch', vi.fn(() =>
      Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(roster) })))
    const wrapper = mount(NMessageProvider, {
      global: { plugins: [createPinia()] },
      slots: { default: () => h(DutyRosterSection, { semesterId: 1, admin: true }) },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('行政值日')
    expect(wrapper.text()).toContain('张主任')
    expect(wrapper.text()).toContain('李副主任')
    expect(wrapper.find('[data-testid="duty-swap-row"]').exists()).toBe(true)
  })
})
