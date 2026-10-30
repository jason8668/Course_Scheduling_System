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

  it('#10 回归:须改密的纯教师进改密页不能被教师清单挡回课表查询', () => {
    // 顺序是关键:改密检查必须在教师清单检查之前,否则“去改密 → 不在清单 → 回课表查询
    // → 又要求改密”互踢,界面卡在 /login 动不了。
    const a = auth(['teacher'], { mustChange: true })
    expect(decideRoute(a, 'change-password', false, null)).toBe(true)
    expect(decideRoute(a, 'dashboard', false, null)).toBe('change-password')
  })

  it('主任/管理员:初始设置未完成时导向精灵,完成后放行', () => {
    const a = auth(['director'])
    expect(decideRoute(a, 'dashboard', false, { completed: false })).toBe('wizard')
    expect(decideRoute(a, 'dashboard', false, { completed: true })).toBe(true)
    expect(decideRoute(a, 'wizard', false, { completed: false })).toBe(true)
    expect(decideRoute(a, 'dashboard', false, null)).toBe(true)
  })

  it('纯教师不触发精灵引导', () => {
    expect(decideRoute(auth(['teacher']), 'dashboard', false, { completed: false })).toBe(true)
  })
})
