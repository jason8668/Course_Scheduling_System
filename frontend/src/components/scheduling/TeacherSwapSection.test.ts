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
  it('教师模式不调主任接口,用已发布课表拼下拉,也不弹载入失败', async () => {
    // 教师模式下 listTeachers/listClassUnits/listAssignments 一律 403,
    // 之前 Promise.all 一挂就弹「载入调课失败/权限不足」;现在教师走已发布课表。
    const called: string[] = []
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      called.push(url)
      if (url.includes('/teacher-swaps')) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(swaps) })
      }
      if (url.includes('/published/timetable')) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({
          entries: [{
            id: 1, course_assignment_id: 1, weekday: 1, period_no: 1, span: 1, locked: false,
            subject: '语文', teachers: ['李老师'], classes: ['七(1)班'], unit_type: 'single',
            unit_name: '', room: null, teacher_ids: [1], class_ids: [1], room_id: null,
          }],
          classes: [{ id: 1, name: '七(1)班', grade: 7, period_table_id: null }],
          teachers: [{ id: 1, name: '李老师' }, { id: 2, name: '王老师' }],
          rooms: [], period_tables: [],
        }) })
      }
      if (url.includes('/published/my-teacher')) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ id: 2, name: '王老师' }) })
      }
      return Promise.resolve({ ok: false, status: 403, json: () => Promise.resolve({ detail: '权限不足' }) })
    }))
    const wrapper = mount(NMessageProvider, {
      slots: { default: () => h(TeacherSwapSection, { semesterId: 1, admin: false }) },
    })
    await flushPromises()
    expect(called.some((u) => u.includes('/teachers') && !u.includes('my-teacher'))).toBe(false)
    expect(called.some((u) => u.includes('/class-units'))).toBe(false)
    expect(called.some((u) => u.includes('/assignments'))).toBe(false)
    expect(wrapper.find('[data-testid="swap-row"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('载入调课失败')
  })

  it('教师发起表单只列自己的课,对调老师不含自己', async () => {
    // 登录老师是王老师(id 2):已发布课表里李老师的语文课不是他的,
    // 王老师自己的数学课才是;对调下拉应有李老师、没有王老师。
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (url.includes('/teacher-swaps')) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) })
      }
      if (url.includes('/published/timetable')) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({
          entries: [
            {
              id: 1, course_assignment_id: 1, weekday: 1, period_no: 1, span: 1, locked: false,
              subject: '语文', teachers: ['李老师'], classes: ['七(1)班'], unit_type: 'single',
              unit_name: '', room: null, teacher_ids: [1], class_ids: [1], room_id: null,
            },
            {
              id: 2, course_assignment_id: 2, weekday: 1, period_no: 1, span: 1, locked: false,
              subject: '数学', teachers: ['王老师'], classes: ['七(2)班'], unit_type: 'single',
              unit_name: '', room: null, teacher_ids: [2], class_ids: [2], room_id: null,
            },
          ],
          classes: [
            { id: 1, name: '七(1)班', grade: 7, period_table_id: null },
            { id: 2, name: '七(2)班', grade: 7, period_table_id: null },
          ],
          teachers: [{ id: 1, name: '李老师' }, { id: 2, name: '王老师' }],
          rooms: [], period_tables: [],
        }) })
      }
      if (url.includes('/published/my-teacher')) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ id: 2, name: '王老师' }) })
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) })
    }))
    const wrapper = mount(NMessageProvider, {
      slots: { default: () => h(TeacherSwapSection, { semesterId: 1, admin: false }) },
    })
    await flushPromises()
    // 旧的班级/配课/原任下拉已不存在,新表单只有我的课 + 对调老师
    expect(wrapper.find('[data-testid="swap-class"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="swap-assignment"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="swap-original"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="swap-my-entry"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="swap-handler"]').exists()).toBe(true)
  })

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
