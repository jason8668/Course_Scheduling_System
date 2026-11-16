import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import Portal from './Portal.vue'
import { useAuthStore } from '@/stores/auth'

// 首页信息区按真实接口取数:这里用 URL 分发的 fetch stub 回固定夹具,
// 不碰后端、不编业务数字以外的假数据。
const TODAY = new Date()
const TODAY_ISO = `${TODAY.getFullYear()}-${String(TODAY.getMonth() + 1).padStart(2, '0')}-${String(TODAY.getDate()).padStart(2, '0')}`
const WEEKDAY = TODAY.getDay() === 0 ? 7 : TODAY.getDay()
const IN_4_DAYS = new Date(TODAY.getTime() + 4 * 86400000)
const IN_4_DAYS_ISO = `${IN_4_DAYS.getFullYear()}-${String(IN_4_DAYS.getMonth() + 1).padStart(2, '0')}-${String(IN_4_DAYS.getDate()).padStart(2, '0')}`
const IN_4_DAYS_LABEL = `${IN_4_DAYS.getMonth() + 1}月${IN_4_DAYS.getDate()}日`
// 迷你校历卡夹具:本月 15 日放假(红点)、20 日活动(蓝点)
const CAL_15 = `${TODAY.getFullYear()}-${String(TODAY.getMonth() + 1).padStart(2, '0')}-15`
const CAL_20 = `${TODAY.getFullYear()}-${String(TODAY.getMonth() + 1).padStart(2, '0')}-20`

function json(data: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(data) })
}

// 记录每次请求的 URL,供调代课筛选测试断言(教师调 mine=true,管理员不调)
const seenUrls: string[] = []

function defaultFetch(url: unknown) {
  const u = String(url)
  seenUrls.push(u)
  if (u.includes('/published/semesters')) {
    return json([{
      id: 1, label: '2026-2027学年第一学期', start_date: '2026-09-01',
      end_date: '2027-01-31', current_week_number: 11, current_week_parity: 'odd',
    }])
  }
  if (u.includes('/semesters')) {
    return json([{
      id: 1, academic_year: 2026, term: 1, label: '2026-2027学年第一学期',
      status: 'active', start_date: '2026-09-01', end_date: '2027-01-31',
    }])
  }
  if (u.includes('/daily-board')) {
    // mine=true 是教师的筛选口径:夹具只回 1 条与他有关的、待处理的
    if (u.includes('mine=true')) {
      return json({
        date: TODAY_ISO, weekday: WEEKDAY, school_name: '', semester_label: '',
        entries: [{ disposed: false }],
      })
    }
    return json({
      date: TODAY_ISO, weekday: WEEKDAY, school_name: '', semester_label: '',
      entries: [{ disposed: false }, { disposed: false }, { disposed: true }],
    })
  }
  if (u.includes('/calendar-events')) {
    return json([
      {
        id: 1, semester_id: 1, title: '国庆节', event_type: 'holiday', scope_type: 'school',
        scope_id: null, start_date: CAL_15, end_date: CAL_15,
        period_start: null, period_end: null, weekly_recurring: false,
        note: '系统自动同步：公共假日', created_by: null, created_at: '', updated_at: '',
      },
      {
        id: 2, semester_id: 1, title: '运动会', event_type: 'activity', scope_type: 'school',
        scope_id: null, start_date: CAL_20, end_date: CAL_20,
        period_start: null, period_end: null, weekly_recurring: false,
        note: null, created_by: null, created_at: '', updated_at: '',
      },
    ])
  }
  if (u.includes('/duty-roster')) {
    return json({
      patterns: [{ id: 1, weekday: WEEKDAY, teacher_id: 2, teacher_name: '值日老师' }],
      overrides: [], swap_requests: [], eligible: [],
    })
  }
  if (u.includes('/teaching-hours/mine')) {
    const month = u.includes('scope=month')
    return json({
      semester_id: 1, date_from: '', date_to: '', effective_from: '', effective_to: '',
      teachers: [{
        teacher_id: 1, teacher_name: '我', total: month ? 12 : 120,
        by_grade: {}, substitute_total: month ? 2 : 5,
      }],
      total_periods: 0,
    })
  }
  if (u.includes('/exam/exams/7/score-progress')) {
    return json({
      subjects: [{
        subject_id: 1, subject_name: '数学',
        classes: [{ class_unit_id: 1, class_name: '七(1)班', total: 40, entered: 32, submitted: 30, status: '' }],
      }],
    })
  }
  if (u.includes('/exam/exams/7/score-change-requests')) {
    return json({ items: [{ id: 1 }], total: 1 })
  }
  if (u.includes('/exam/exams/7/proofreading')) {
    return json({ items: [{ id: 1, status: '待校对' }, { id: 2, status: '通过' }], total: 2 })
  }
  if (u.includes('/exam/exams/7')) {
    return json({
      id: 7, semester_id: 1, name: '期中考试', exam_type: '期中', grades: [7, 8, 9],
      status: '成绩处理中', description: null, created_at: '2026-11-10T00:00:00',
      subjects: [{
        subject_id: 1, subject_name: '数学', exam_date: IN_4_DAYS_ISO,
        start_time: '09:00', end_time: '11:00', full_score: 100,
      }],
      participant_count: 120,
    })
  }
  if (u.includes('/exam/exams')) {
    return json({
      items: [
        {
          id: 7, semester_id: 1, name: '期中考试', exam_type: '期中', grades: [7, 8, 9],
          status: '成绩处理中', description: null, created_at: '2026-11-10T00:00:00',
        },
        {
          id: 6, semester_id: 1, name: '十月月考', exam_type: '月考', grades: [7, 8, 9],
          status: '已发布成绩', description: null, created_at: '2026-10-20T00:00:00',
        },
      ],
      total: 2,
    })
  }
  if (u.includes('/auth/logout')) return json({})
  return json({})
}

beforeEach(() => {
  seenUrls.length = 0
  vi.stubGlobal('fetch', vi.fn((url: unknown) => defaultFetch(url)))
})

function setup(roles: string[] = ['admin']) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.user = {
    id: 1, username: 'admin', display_name: '系统管理员', roles,
    must_change_password: false,
  }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'portal', component: Portal },
      { path: '/scheduling-center', name: 'scheduling-center', component: { template: '<div />' } },
      { path: '/exam/students', name: 'exam-students', component: { template: '<div />' } },
      { path: '/asset/workspace', name: 'asset-workspace', component: { template: '<div />' } },
      { path: '/exam/exams', name: 'exam-exams', component: { template: '<div />' } },
      { path: '/exam/exams/:id', name: 'exam-exam-detail', component: { template: '<div />' } },
      { path: '/exam/exams/:id/scores', name: 'exam-exam-scores', component: { template: '<div />' } },
      { path: '/exam/exams/:id/publish', name: 'exam-exam-publish', component: { template: '<div />' } },
      { path: '/substitution-center', name: 'substitution-center', component: { template: '<div />' } },
      { path: '/school-calendar', name: 'school-calendar', component: { template: '<div />' } },
      { path: '/login', name: 'login', component: { template: '<div />' } },
      { path: '/change-password', name: 'change-password', component: { template: '<div />' } },
    ],
  })
  return { pinia, router }
}

async function mountPortal(roles: string[] = ['admin']) {
  const { pinia, router } = setup(roles)
  await router.push('/')
  await router.isReady()
  const wrapper = mount(Portal, {
    global: { plugins: [pinia, router] },
  })
  // 首页信息是多轮异步取数:多 flush 几轮等链路跑完
  await flushPromises()
  await flushPromises()
  await flushPromises()
  return { wrapper, router }
}

describe('Portal', () => {
  it('只排三个已建成系统的入口卡,标题与副标题正确', async () => {
    const { wrapper } = await mountPortal()
    expect(wrapper.text()).toContain('智慧教务系统')
    expect(wrapper.text()).toContain('一个账号，进各个系统')
    expect(wrapper.find('[data-testid="entry-scheduling"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="entry-scheduling"]').text()).toContain('排课系统')
    expect(wrapper.find('[data-testid="entry-exam"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="entry-exam"]').text()).toContain('考务成绩系统')
    expect(wrapper.find('[data-testid="entry-asset"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="entry-asset"]').text()).toContain('资产管理系统')
    // 没建成的系统不画占位卡片:入口卡正好三张
    expect(wrapper.findAll('.entry-card').length).toBe(3)
  })

  it('点排课卡进排课中心,点考务卡进学生档案,点资产卡进我的工作台', async () => {
    const { wrapper, router } = await mountPortal()
    await wrapper.find('[data-testid="entry-scheduling"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('scheduling-center')
    await router.push('/')
    await wrapper.find('[data-testid="entry-exam"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('exam-students')
    await router.push('/')
    await wrapper.find('[data-testid="entry-asset"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('asset-workspace')
  })

  it('独立页:不带系统边栏,只留账号操作(改密、退出)', async () => {
    const { wrapper, router } = await mountPortal()
    // 右上角显示登录账号名,有改密与退出,能正常退出回登录页
    expect(wrapper.text()).toContain('系统管理员')
    expect(wrapper.find('[data-testid="portal-change-password"]').exists()).toBe(true)
    await wrapper.find('[data-testid="portal-logout"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('login')
    // 边栏菜单不在总入口页上:排课系统的菜单项一个都不该出现
    expect(wrapper.text()).not.toContain('排课中心')
    expect(wrapper.text()).not.toContain('调代课中心')
    expect(wrapper.text()).not.toContain('仪表板')
  })

  it('今日概览:日期、学期、第几周、值日、调代课数都来自接口', async () => {
    const { wrapper } = await mountPortal()
    const today = wrapper.find('[data-testid="portal-today"]')
    expect(today.exists()).toBe(true)
    expect(today.text()).toContain(`${TODAY.getMonth() + 1}月${TODAY.getDate()}日`)
    expect(today.text()).toContain('2026-2027学年第一学期')
    expect(today.text()).toContain('第 11 周')
    expect(today.text()).toContain('值日老师')
    expect(today.text()).toContain('3 条 · 待处理 2 条')
    // 管理员看全校:调代课请求不带 mine=true
    expect(seenUrls.filter((u) => u.includes('/daily-board'))
      .every((u) => !u.includes('mine=true'))).toBe(true)
  })

  it('调代课筛选:教师首页只调 mine=true 的接口,数是筛选后的', async () => {
    const { wrapper } = await mountPortal(['teacher'])
    const today = wrapper.find('[data-testid="portal-today"]')
    expect(today.text()).toContain('1 条 · 待处理 1 条')
    expect(seenUrls.some((u) => u.includes('/daily-board') && u.includes('mine=true'))).toBe(true)
  })

  it('我的课时:本月与本学期已上节数、其中代课节数', async () => {
    const { wrapper } = await mountPortal()
    const hours = wrapper.find('[data-testid="portal-hours"]')
    expect(hours.exists()).toBe(true)
    expect(hours.text()).toContain('本月已上')
    expect(hours.text()).toContain('12 节')
    expect(hours.text()).toContain('其中代课 2 节')
    expect(hours.text()).toContain('本学期已上')
    expect(hours.text()).toContain('120 节')
  })

  it('考试进行时:管理员看最近考试、最近场次、录分进度与待办', async () => {
    const { wrapper } = await mountPortal(['admin'])
    const exam = wrapper.find('[data-testid="portal-exam"]')
    expect(exam.exists()).toBe(true)
    expect(exam.text()).toContain('期中考试')
    expect(exam.text()).toContain('成绩处理中')
    expect(exam.text()).toContain(`${IN_4_DAYS_LABEL} 09:00–11:00 · 数学`)
    expect(exam.text()).toContain('最近已发布成绩：十月月考')
    expect(exam.text()).toContain('已录 32 / 应录 40')
    expect(exam.text()).toContain('待校对 1 项')
    expect(exam.text()).toContain('待审批改分 1 条')
  })

  it('教师看考试进行时:只看最近考试,不看全校录分进度与待办', async () => {
    const { wrapper } = await mountPortal(['teacher'])
    const exam = wrapper.find('[data-testid="portal-exam"]')
    expect(exam.exists()).toBe(true)
    expect(exam.text()).toContain('期中考试')
    expect(exam.text()).toContain(`${IN_4_DAYS_LABEL} 09:00–11:00 · 数学`)
    expect(exam.text()).not.toContain('录分进度')
    expect(exam.text()).not.toContain('待校对')
    expect(exam.text()).not.toContain('待审批改分')
  })

  it('迷你校历卡:在今日概览行右侧,月份标题是本月,放假日打红点', async () => {
    const { wrapper } = await mountPortal()
    expect(wrapper.find('[data-testid="portal-top-row"]').exists()).toBe(true)
    const card = wrapper.find('[data-testid="portal-calendar"]')
    expect(card.exists()).toBe(true)
    expect(card.text()).toContain(`${TODAY.getFullYear()}年${TODAY.getMonth() + 1}月`)
    const holidayDot = wrapper.find(`[data-iso="${CAL_15}"] .cal-dot`)
    expect(holidayDot.exists()).toBe(true)
    expect(holidayDot.classes()).toContain('dot-holiday')
    const activityDot = wrapper.find(`[data-iso="${CAL_20}"] .cal-dot`)
    expect(activityDot.exists()).toBe(true)
    expect(activityDot.classes()).not.toContain('dot-holiday')
  })

  it('迷你校历卡:完整校历链接跳 school-calendar', async () => {
    const { wrapper, router } = await mountPortal()
    await wrapper.find('[data-testid="portal-calendar-full"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('school-calendar')
  })

  it('本学期无考试时显示空态,不画假考试', async () => {
    vi.stubGlobal('fetch', vi.fn((url: unknown) => {
      const u = String(url)
      if (u.includes('/exam/exams') && !u.includes('/exam/exams/')) {
        return json({ items: [], total: 0 })
      }
      return defaultFetch(url)
    }))
    const { wrapper } = await mountPortal()
    expect(wrapper.find('[data-testid="portal-exam"]').exists()).toBe(false)
    const empty = wrapper.find('[data-testid="portal-exam-empty"]')
    expect(empty.exists()).toBe(true)
    expect(empty.text()).toContain('本学期暂无考试')
  })
})
