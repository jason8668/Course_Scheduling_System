import { flushPromises, mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import TeacherSwapSection from './TeacherSwapSection.vue'

// 老师调课段只做两件事:列出调课记录,待确认的给对方留同意按钮。
const swaps = [{
  id: 1, semester_id: 1, requester_id: 1, status: 'pending', note: null,
  class_date: '2026-11-02', period_no: 1, class_unit_id: 1, course_assignment_id: 1,
  original_teacher_id: 1, handler_teacher_id: 2,
  makeup_date: null, makeup_period_no: null, makeup_class_unit_id: null,
  makeup_assignment_id: null, approver_teacher_id: 2, is_retroactive: false,
}]

describe('TeacherSwapSection', () => {
  it('管理员模式列出调课记录', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (url.includes('/teacher-swaps')) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(swaps) })
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) })
    }))
    const wrapper = mount(NMessageProvider, {
      slots: { default: () => h(TeacherSwapSection, { semesterId: 1, admin: true }) },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('老师调课')
    expect(wrapper.find('[data-testid="swap-row"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('待对方确认')
  })
})
