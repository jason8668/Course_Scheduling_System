import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useWizardStore } from '@/stores/wizard'
import { AUTH_PAGES, decideRoute } from './guard'

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

// 全域守卫:管控登录、强制改密、首次登录引导至设置精灵。
// “去哪”的决策在 ./guard.ts(纯函数,可单测);这里只负责拉取状态。
router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.loaded) {
    await auth.fetchMe()
  }

  let wizardState = null
  const canSetup = auth.hasRole('director') || auth.hasRole('admin')
  if (canSetup && to.name !== 'wizard' && !AUTH_PAGES.has(to.name as string)) {
    const wizard = useWizardStore()
    if (!wizard.loaded) await wizard.fetch()
    wizardState = wizard.state
  }

  const next = decideRoute(
    auth,
    to.name as string,
    !!to.meta.public,
    wizardState,
  )
  return next === true ? true : { name: next }
})
