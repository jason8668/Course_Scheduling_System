// 路由守卫的纯决策部分(与 router/index.ts 的 beforeEach 同款逻辑,抽出来只为可测)。
// beforeEach 只负责拉取状态(auth.fetchMe / wizard.fetch),真正“去哪”由这里定,
// 这样 #10 那种互踢循环(改密码页被教师清单挡回)能在单测里直接验到,不用挂整个路由。

export const AUTH_PAGES = new Set(['login', 'change-password'])

// 纯教师帐号可进入的页面(请假是教师自己要做的事;课表打印页是查课表后打印用)
export const TEACHER_PAGES = new Set([
  'dashboard', 'my', 'school-calendar', 'calendar-print',
  'timetable-query', 'timetable-print', 'leaves', 'substitution-stats',
])

export interface GuardAuth {
  isAuthenticated: boolean
  mustChangePassword: boolean
  hasRole: (role: string) => boolean
}

export interface WizardState {
  completed: boolean
}

/** 回传 true = 放行,回传名字 = 导向该路由。 */
export function decideRoute(
  auth: GuardAuth,
  toName: string | null | undefined,
  isPublic: boolean,
  wizardState: WizardState | null,
): true | string {
  const name = toName ?? ''
  if (isPublic) {
    if (auth.isAuthenticated && name === 'login') {
      return auth.mustChangePassword ? 'change-password' : 'dashboard'
    }
    return true
  }

  if (!auth.isAuthenticated) {
    return 'login'
  }
  if (auth.mustChangePassword && name !== 'change-password') {
    return 'change-password'
  }

  // 纯教师帐号:只开放课表查询与请假登记(其余页面的后端 API 皆需主任以上权限)。
  // 改密码页必须排除:否则首次登录的教师会被「导去改密码 → 不在教师可进清单 → 导回课表查询
  // → 又要求改密码」互踢,界面卡在 /login 动不了(#10)。
  const canManage = auth.hasRole('admin') || auth.hasRole('director')
  if (
    !canManage && auth.hasRole('teacher')
    && !AUTH_PAGES.has(name) && !TEACHER_PAGES.has(name)
  ) {
    return 'timetable-query'
  }

  // 首次登录引导:年级主任/管理员在尚未完成初始设置时,自动进入精灵(精灵内可略过)
  const canSetup = auth.hasRole('director') || auth.hasRole('admin')
  if (canSetup && name !== 'wizard' && !AUTH_PAGES.has(name)) {
    if (wizardState && !wizardState.completed) {
      return 'wizard'
    }
  }
  return true
}
