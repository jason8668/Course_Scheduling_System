import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useWizardStore } from '@/stores/wizard'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true },
  },
  {
    path: '/change-password',
    name: 'change-password',
    component: () => import('@/views/ChangePassword.vue'),
  },
  {
    path: '/wizard',
    name: 'wizard',
    component: () => import('@/views/wizard/Wizard.vue'),
  },
  {
    // 独立 A4 通知单打印页,不套用侧边栏版面(干净一页供打印)
    path: '/daily-board/print',
    name: 'daily-board-print',
    component: () => import('@/views/substitution/DailyBoardPrint.vue'),
  },
  {
    // 调课通知单(教师/班级)打印页,同样不套侧边栏
    path: '/swap-slips/print',
    name: 'swap-slips-print',
    component: () => import('@/views/substitution/SlipsPrint.vue'),
  },
  {
    // 代课通知单(教师/班级)打印页:与调课单同一个元件,版面相同、表头不同
    path: '/substitute-slips/print',
    name: 'substitute-slips-print',
    component: () => import('@/views/substitution/SlipsPrint.vue'),
  },
  {
    // 课堂巡视情况记录表打印页(A4 横式),不套侧边栏
    path: '/patrol-sheets/print',
    name: 'patrol-sheets-print',
    component: () => import('@/views/substitution/PatrolPrint.vue'),
  },
  {
    // 教学课时统计打印页(A4 直式,按年级分组),不套侧边栏
    path: '/teaching-hours/print',
    name: 'teaching-hours-print',
    component: () => import('@/views/substitution/TeachingHoursPrint.vue'),
  },
  {
    // 课表打印页(班级/教师/场地三种视角共用),供打印张贴,不套侧边栏
    path: '/timetable/print',
    name: 'timetable-print',
    component: () => import('@/views/TimetablePrint.vue'),
  },
  {
    // 校历打印页:本学期全部校历一页一览,供 A4 打印张贴,不套侧边栏
    path: '/calendar/print',
    name: 'calendar-print',
    component: () => import('@/views/CalendarPrint.vue'),
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    children: [
      {
        path: '',
        name: 'dashboard',
        component: () => import('@/views/Dashboard.vue'),
      },
      {
        path: 'my',
        name: 'my',
        redirect: { name: 'dashboard' },
      },
      {
        path: 'settings/semesters',
        name: 'semesters',
        component: () => import('@/views/settings/Semesters.vue'),
      },
      {
        path: 'setup-flow',
        name: 'setup-flow',
        component: () => import('@/views/setup/SetupFlow.vue'),
      },
      {
        path: 'stats-center',
        name: 'stats-center',
        component: () => import('@/views/stats/StatsCenter.vue'),
      },
      {
        path: 'basedata',
        name: 'basedata',
        component: () => import('@/views/basedata/BaseData.vue'),
      },
      {
        path: 'scheduling-center',
        name: 'scheduling-center',
        component: () => import('@/views/scheduling/SchedulingCenter.vue'),
      },
      {
        path: 'scheduling/assignments',
        name: 'assignments',
        component: () => import('@/views/scheduling/Assignments.vue'),
      },
      {
        path: 'timetable-query',
        name: 'timetable-query',
        component: () => import('@/views/TimetableQuery.vue'),
      },
      {
        path: 'school-calendar',
        name: 'school-calendar',
        component: () => import('@/views/SchoolCalendar.vue'),
      },
      {
        path: 'scheduling/workbench',
        name: 'workbench',
        component: () => import('@/views/scheduling/Workbench.vue'),
      },
      {
        path: 'scheduling/auto',
        name: 'auto-schedule',
        component: () => import('@/views/scheduling/AutoSchedule.vue'),
      },
      {
        path: 'leaves',
        name: 'leaves',
        component: () => import('@/views/leaves/Leaves.vue'),
      },
      {
        path: 'substitution-center',
        name: 'substitution-center',
        component: () => import('@/views/substitution/SubstitutionCenter.vue'),
      },
      {
        path: 'substitutions',
        name: 'substitutions',
        component: () => import('@/views/substitution/Substitutions.vue'),
      },
      {
        path: 'notification-board',
        name: 'notification-board',
        component: () => import('@/views/substitution/NotificationBoard.vue'),
      },
      {
        path: 'daily-board',
        name: 'daily-board',
        component: () => import('@/views/substitution/DailyBoard.vue'),
      },
      {
        path: 'substitution-log',
        name: 'substitution-log',
        component: () => import('@/views/substitution/SubstitutionLog.vue'),
      },
      {
        path: 'substitution-stats',
        name: 'substitution-stats',
        component: () => import('@/views/substitution/SubstitutionStats.vue'),
      },
      {
        path: 'substitution/teaching-hours',
        name: 'teaching-hours',
        component: () => import('@/views/substitution/TeachingHours.vue'),
      },
      {
        path: 'scheduling/versions',
        name: 'versions',
        component: () => import('@/views/scheduling/Versions.vue'),
      },
      {
        path: 'scheduling/timetable-demo',
        name: 'timetable-demo',
        component: () => import('@/views/scheduling/TimetableGridDemo.vue'),
      },
      {
        path: 'settings/period-tables/:id',
        name: 'period-table-editor',
        component: () => import('@/views/settings/PeriodTableEditor.vue'),
      },
      {
        path: 'settings/system',
        name: 'system',
        component: () => import('@/views/settings/System.vue'),
      },
    ],
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

const AUTH_PAGES = new Set(['login', 'change-password'])

// 全域守卫:管控登录、强制改密、首次登录引导至设置精灵
// 纯教师帐号可进入的页面(请假是教师自己要做的事;课表打印页是查课表后打印自己/班级课表用)
const TEACHER_PAGES = new Set([
  'dashboard', 'my', 'school-calendar', 'calendar-print',
  'timetable-query', 'timetable-print', 'leaves', 'substitution-stats',
])

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.loaded) {
    await auth.fetchMe()
  }

  if (to.meta.public) {
    if (auth.isAuthenticated && to.name === 'login') {
      return { name: auth.mustChangePassword ? 'change-password' : 'dashboard' }
    }
    return true
  }

  if (!auth.isAuthenticated) {
    return { name: 'login' }
  }
  if (auth.mustChangePassword && to.name !== 'change-password') {
    return { name: 'change-password' }
  }

  // 纯教师帐号:只开放课表查询与请假登记(其余页面的后端 API 皆需主任以上权限)。
  // 改密码页必须排除:否则首次登录的教师会被「导去改密码 → 不在教师可进清单 → 导回课表查询
  // → 又要求改密码」互踢,界面卡在 /login 动不了(#10)。
  const canManage = auth.hasRole('admin') || auth.hasRole('director')
  if (
    !canManage && auth.hasRole('teacher')
    && !AUTH_PAGES.has(to.name as string) && !TEACHER_PAGES.has(to.name as string)
  ) {
    return { name: 'timetable-query' }
  }

  // 首次登录引导:年级主任/管理员在尚未完成初始设置时,自动进入精灵(精灵内可略过)
  const canSetup = auth.hasRole('director') || auth.hasRole('admin')
  if (canSetup && to.name !== 'wizard' && !AUTH_PAGES.has(to.name as string)) {
    const wizard = useWizardStore()
    if (!wizard.loaded) await wizard.fetch()
    if (wizard.state && !wizard.state.completed) {
      return { name: 'wizard' }
    }
  }
  return true
})
