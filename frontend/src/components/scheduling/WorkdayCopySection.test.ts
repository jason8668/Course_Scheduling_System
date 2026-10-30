import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { NMessageProvider } from 'naive-ui'
import { describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import WorkdayCopySection from './WorkdayCopySection.vue'
import { useAuthStore } from '@/stores/auth'

// 调休复制区只做两件事:列出调休日并标出 14 天内待复制,管理员一键复制某天课表。
// 日期用远期固定日会算成“还有很多天”,故用相对今天 +5 天的调休日测紧急提醒。
function futureDate(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() + days)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

describe('WorkdayCopySection', () => {
  it('14 天内未复制的调休日醒目提醒,已复制的显示已复制', async () => {
    const soon = futureDate(5)
    const later = futureDate(30)
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (url.includes('/calendar-events/workdays')) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([
          { date: soon, title: '国庆节调休上班', has_copy: false },
          { date: later, title: '春节调休上班', has_copy: true },
        ]) })
      }
      if (url.includes('/published/timetable')) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({
          entries: [], classes: [], teachers: [], rooms: [], period_tables: [],
        }) })
      }
      if (url.includes('/semesters/')) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({
          id: 1, start_date: '2026-09-01', end_date: '2027-01-31', period_tables: [],
        }) })
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) })
    }))
    const pinia = createPinia()
    const wrapper = mount(NMessageProvider, {
      global: { plugins: [pinia] },
      slots: { default: () => h(WorkdayCopySection, { semesterId: 1 }) },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('国庆节调休上班')
    expect(wrapper.text()).toContain('请联系管理员复制')
    expect(wrapper.find('[data-testid="workday-row"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('已复制')
  })

  it('管理员一键复制按周五课表,调特殊日创建+发布接口', async () => {
    const soon = futureDate(5)
    const called: string[] = []
    vi.stubGlobal('fetch', vi.fn((url: string, opts?: { method?: string }) => {
      called.push(`${opts?.method ?? 'GET'} ${url}`)
      if (url.includes('/calendar-events/workdays')) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([
          { date: soon, title: '国庆节调休上班', has_copy: false },
        ]) })
      }
      if (url.includes('/published/timetable')) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({
          entries: [{
            id: 1, course_assignment_id: 7, weekday: 5, period_no: 1, span: 1, locked: false,
            subject: '数学', teachers: ['王老师'], classes: ['七(1)班'], unit_type: 'single',
            unit_name: '', room: null, teacher_ids: [1], class_ids: [1], room_id: null,
          }],
          classes: [{ id: 1, name: '七(1)班', grade: 7, period_table_id: null }],
          teachers: [{ id: 1, name: '王老师' }],
          rooms: [], period_tables: [],
        }) })
      }
      if (url.includes('/semesters/')) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({
          id: 1, start_date: '2026-09-01', end_date: '2027-01-31', period_tables: [],
        }) })
      }
      if (url.includes('/special-days') && (opts?.method ?? 'GET') === 'POST') {
        return Promise.resolve({ ok: true, status: 201, json: () => Promise.resolve({ id: 99 }) })
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) })
    }))
    const pinia = createPinia()
    const wrapper = mount(NMessageProvider, {
      global: { plugins: [pinia] },
      slots: { default: () => h(WorkdayCopySection, { semesterId: 1 }) },
    })
    const auth = useAuthStore(pinia)
    auth.user = {
      id: 1, username: 'adm', display_name: '管理员', roles: ['admin'], must_change_password: false,
    }
    await flushPromises()
    const btn = wrapper.find('[data-testid="workday-copy"]')
    expect(btn.exists()).toBe(true)
    await btn.trigger('click')
    await flushPromises()
    expect(called.some((c) => c.includes('/special-days') && c.includes('POST'))).toBe(true)
    expect(called.some((c) => c.includes('/publish'))).toBe(true)
  })
})
