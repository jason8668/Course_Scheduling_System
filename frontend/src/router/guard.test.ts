import { describe, expect, it } from 'vitest'
import { decideRoute } from './guard'
import type { GuardAuth } from './guard'

function auth(roles: string[], opts: { authed?: boolean; mustChange?: boolean } = {}): GuardAuth {
  return {
    isAuthenticated: opts.authed ?? true,
    mustChangePassword: opts.mustChange ?? false,
    hasRole: (r: string) => roles.includes(r),
  }
}

describe('decideRoute', () => {
  it('未登录一律去登录页(公开页除外)', () => {
    expect(decideRoute(auth([], { authed: false }), 'dashboard', false, null)).toBe('login')
    expect(decideRoute(auth([], { authed: false }), 'login', true, null)).toBe(true)
  })

  it('已登录进登录页:须改密去改密页,否则去仪表板', () => {
    expect(decideRoute(auth(['teacher']), 'login', true, null)).toBe('dashboard')
    expect(decideRoute(auth(['teacher'], { mustChange: true }), 'login', true, null))
      .toBe('change-password')
  })

  it('须改密时除改密页外一律去改密页', () => {
    const a = auth(['director'], { mustChange: true })
    expect(decideRoute(a, 'dashboard', false, null)).toBe('change-password')
    expect(decideRoute(a, 'change-password', false, null)).toBe(true)
  })

  it('纯教师:教师清单内的页放行,清单外的导回课表查询', () => {
    const a = auth(['teacher'])
    expect(decideRoute(a, 'leaves', false, null)).toBe(true)
    expect(decideRoute(a, 'timetable-query', false, null)).toBe(true)
    expect(decideRoute(a, 'scheduling-center', false, null)).toBe('timetable-query')
    expect(decideRoute(a, 'system', false, null)).toBe('timetable-query')
  })

  it('纯教师:考务入口三页放行(班主任要看本班学生档案)', () => {
    const a = auth(['teacher'])
    expect(decideRoute(a, 'exam-students', false, null)).toBe(true)
    expect(decideRoute(a, 'exam-subject-settings', false, null)).toBe(true)
    expect(decideRoute(a, 'exam-number-rule', false, null)).toBe(true)
  })

  it('纯教师:考试管理两页放行(班主任要看本班参试名单)', () => {
    const a = auth(['teacher'])
    expect(decideRoute(a, 'exam-exams', false, null)).toBe(true)
    expect(decideRoute(a, 'exam-exam-detail', false, null)).toBe(true)
  })

  it('纯教师:考场编排页放行(班主任要看本班考场座位)', () => {
    const a = auth(['teacher'])
    expect(decideRoute(a, 'exam-exam-arrange', false, null)).toBe(true)
  })

  it('纯教师:三张打印页放行(班主任打准考证、监考教师打签到表)', () => {
    const a = auth(['teacher'])
    expect(decideRoute(a, 'exam-exam-admission-tickets', false, null)).toBe(true)
    expect(decideRoute(a, 'exam-exam-attendance-sheets', false, null)).toBe(true)
    expect(decideRoute(a, 'exam-exam-door-labels', false, null)).toBe(true)
  })

  it('纯教师:监考安排页放行(监考教师要看本人监考场次)', () => {
    const a = auth(['teacher'])
    expect(decideRoute(a, 'exam-exam-invigilation', false, null)).toBe(true)
  })

  it('纯教师:成绩录入页放行(任课教师要录本人所教班级科目)', () => {
    const a = auth(['teacher'])
    expect(decideRoute(a, 'exam-exam-scores', false, null)).toBe(true)
  })

  it('纯教师:发布与校对锁定页放行(教师要看本人成绩的校对与异议)', () => {
    const a = auth(['teacher'])
    expect(decideRoute(a, 'exam-exam-publish', false, null)).toBe(true)
  })

  it('纯教师:成绩分析页放行(班主任要看本班分析)', () => {
    const a = auth(['teacher'])
    expect(decideRoute(a, 'exam-exam-analysis', false, null)).toBe(true)
  })

  it('纯教师:成绩单三页放行(班主任要打本班成绩单)', () => {
    const a = auth(['teacher'])
    expect(decideRoute(a, 'exam-exam-report-class', false, null)).toBe(true)
    expect(decideRoute(a, 'exam-exam-report-student', false, null)).toBe(true)
    expect(decideRoute(a, 'exam-exam-teacher-scores', false, null)).toBe(true)
    expect(decideRoute(a, 'exam-my-scores', false, null)).toBe('timetable-query')
    expect(decideRoute(a, 'exam-exam-accounts', false, null)).toBe('timetable-query')
  })

  it('纯教师:通知与提醒页放行(教师要看发给本人的通知记录)', () => {
    const a = auth(['teacher'])
    expect(decideRoute(a, 'exam-exam-notifications', false, null)).toBe(true)
  })

  it('纯教师:归档与备份页不放行(教务功能，导回课表查询)', () => {
    const a = auth(['teacher'])
    expect(decideRoute(a, 'exam-exam-archive', false, null)).toBe('timetable-query')
  })

  it('学生/家长:登录后落地自助查询页,只能进自助查询页与改密页', () => {
    const s = auth(['student'])
    const p = auth(['parent'])
    expect(decideRoute(s, 'login', true, null)).toBe('exam-my-scores')
    expect(decideRoute(p, 'login', true, null)).toBe('exam-my-scores')
    expect(decideRoute(s, 'exam-my-scores', false, null)).toBe(true)
    expect(decideRoute(p, 'exam-my-scores', false, null)).toBe(true)
    expect(decideRoute(s, 'dashboard', false, null)).toBe('exam-my-scores')
    expect(decideRoute(s, 'exam-exams', false, null)).toBe('exam-my-scores')
    expect(decideRoute(s, 'change-password', false, null)).toBe(true)
  })

  it('#10 回归:须改密的纯教师进改密页不能被教师清单挡回课表查询', () => {
    // 顺序是关键:改密检查必须在教师清单检查之前,否则“去改密 → 不在清单 → 回课表查询
    // → 又要求改密”互踢,界面卡在 /login 动不了。
    const a = auth(['teacher'], { mustChange: true })
    expect(decideRoute(a, 'change-password', false, null)).toBe(true)
    expect(decideRoute(a, 'dashboard', false, null)).toBe('change-password')
  })

  it('主任/管理员:初始设置未完成时导向开学建置,完成后放行', () => {
    const a = auth(['director'])
    expect(decideRoute(a, 'dashboard', false, { completed: false })).toBe('setup-flow')
    expect(decideRoute(a, 'dashboard', false, { completed: true })).toBe(true)
    expect(decideRoute(a, 'setup-flow', false, { completed: false })).toBe(true)
    expect(decideRoute(a, 'wizard', false, { completed: false })).toBe(true)
    expect(decideRoute(a, 'dashboard', false, null)).toBe(true)
  })

  it('纯教师不触发精灵引导', () => {
    expect(decideRoute(auth(['teacher']), 'dashboard', false, { completed: false })).toBe(true)
  })
})
