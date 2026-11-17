import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import CalendarPrint from './CalendarPrint.vue'

// 打印页：一学期 5 个月框、一个月一行竖向往下排、一张 A4 竖向放下、字偏小；
// 特殊日期只在日期格里着色写标题，下面不另列一行一行的明细。
const SEMESTER = {
  id: 1, academic_year: 2026, term: 1, label: '2026-2027学年第一学期',
  status: 'active', start_date: '2026-09-01', end_date: '2027-01-31',
}
const EVENTS = [
  {
    id: 1, semester_id: 1, title: '秋季运动会', event_type: 'activity',
    scope_type: 'school', scope_id: null, start_date: '2026-09-18', end_date: '2026-09-18',
    period_start: null, period_end: null, weekly_recurring: false, note: null,
    created_by: 1, created_at: '2026-09-01T00:00:00', updated_at: '2026-09-01T00:00:00',
  },
  {
    id: 2, semester_id: 1, title: '国庆节', event_type: 'holiday',
    scope_type: 'school', scope_id: null, start_date: '2026-10-01', end_date: '2026-10-07',
    period_start: null, period_end: null, weekly_recurring: false, note: null,
    created_by: 1, created_at: '2026-09-01T00:00:00', updated_at: '2026-09-01T00:00:00',
  },
  {
    id: 3, semester_id: 1, title: '期中考试', event_type: 'exam',
    scope_type: 'school', scope_id: null, start_date: '2026-11-09', end_date: '2026-11-11',
    period_start: null, period_end: null, weekly_recurring: false, note: null,
    created_by: 1, created_at: '2026-09-01T00:00:00', updated_at: '2026-09-01T00:00:00',
  },
]

vi.stubGlobal('fetch', vi.fn((url: string) => {
  let body: unknown = {}
  if (url.includes('/published/semesters')) body = [SEMESTER]
  else if (url.includes('/calendar-events')) body = EVENTS
  else if (url.includes('/settings/school')) body = { school_name: '测试学校' }
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) })
}))

async function mountPrint() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/calendar/print', name: 'calendar-print', component: CalendarPrint }],
  })
  await router.push('/calendar/print?semester_id=1')
  await router.isReady()
  const wrapper = mount(CalendarPrint, { global: { plugins: [pinia, router] } })
  await flushPromises()
  await flushPromises()
  return wrapper
}

describe('CalendarPrint', () => {
  it('一学期 5 个月框按顺序竖向排，下面没有一行一行的明细表', async () => {
    const wrapper = await mountPrint()
    const frames = wrapper.findAll('.month-frame')
    expect(frames).toHaveLength(5)
    expect(frames.map((f) => f.find('.month-frame-title').text())).toEqual([
      '2026年9月', '2026年10月', '2026年11月', '2026年12月', '2027年1月',
    ])
    // 只有 5 张月框表：下面没有按日期一行一行列特殊日期的明细表
    expect(wrapper.findAll('table')).toHaveLength(5)
    expect(wrapper.find('[data-testid="cal-frames"]').exists()).toBe(true)
  })

  it('特殊日期只在日期格里显示标题', async () => {
    const wrapper = await mountPrint()
    expect(wrapper.text()).toContain('秋季运动会')
    expect(wrapper.text()).toContain('国庆节')
    expect(wrapper.text()).toContain('期中考试')
    expect(wrapper.text()).toContain('共 3 条活动')
  })
})
