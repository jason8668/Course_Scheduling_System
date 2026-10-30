import { flushPromises, mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import SpecialDaySection from './SpecialDaySection.vue'

// 特殊日编辑段只做两件事:把规则列出来,编辑条目时只给教该班的配课选。
// 拿别的班的配课来换,后端会 400,故这里把下拉的过滤钉死。
const rules = [{
  id: 1, semester_id: 1, title: '运动会日', scope_type: 'school', scope_id: null,
  recurrence: 'single', single_date: '2026-11-02', weekday: null, day_of_month: null,
  start_date: null, end_date: null, is_active: false,
  entries: [{ id: 1, class_unit_id: 1, period_no: 1, course_assignment_id: 10 }],
}]
const classes = [
  { id: 1, semester_id: 1, grade: 7, name: '七年级1班', track: 'junior_high' },
  { id: 2, semester_id: 1, grade: 7, name: '七年级2班', track: 'junior_high' },
]
const assignments = [
  {
    id: 10, semester_id: 1,
    scheduling_unit: { id: 1, semester_id: 1, unit_type: 'single', name: '七年级1班', classes: [{ id: 1, name: '七年级1班', grade: 7 }] },
    subject: { id: 1, name: '语文' }, periods_per_week: 5, required_room_type: null,
    room_id: null, lock_room: false, teachers: [{ teacher_id: 2, is_lead: true, name: '李小红' }],
    block_rules: [], week_parity: null,
  },
  {
    id: 11, semester_id: 1,
    scheduling_unit: { id: 2, semester_id: 1, unit_type: 'single', name: '七年级2班', classes: [{ id: 2, name: '七年级2班', grade: 7 }] },
    subject: { id: 2, name: '数学' }, periods_per_week: 5, required_room_type: null,
    room_id: null, lock_room: false, teachers: [{ teacher_id: 3, is_lead: true, name: '王小明' }],
    block_rules: [], week_parity: null,
  },
]

function stubFetch() {
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    let body: unknown = []
    if (url.includes('/special-days')) body = rules
    else if (url.includes('/class-units')) body = classes
    else if (url.includes('/assignments')) body = assignments
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) })
  }))
}

describe('SpecialDaySection', () => {
  it('列出规则,编辑条目时只显示该班的配课与取消选项', async () => {
    stubFetch()
    const wrapper = mount(NMessageProvider, {
      slots: { default: () => h(SpecialDaySection, { semesterId: 1 }) },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('运动会日')
    // 展开编辑器:当前条目是 1 班第 1 节换语文,下拉选项里应有语文与取消,无数学(2 班的)
    const edit = wrapper.find('[data-testid="sd-edit"]')
    expect(edit.exists()).toBe(true)
    await edit.trigger('click')
    await flushPromises()
    const editor = wrapper.find('[data-testid="sd-editor"]')
    expect(editor.exists()).toBe(true)
    expect(editor.text()).toContain('七年级1班第1节→语文(李小红)')
  })
})
