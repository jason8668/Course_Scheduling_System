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
    // 总主入口:独立页,不套系统边栏(登录页同款干净版面),登录后落点。
    // 所有系统排一张网格上,以后新系统往里加卡。
    path: '/',
    name: 'portal',
    component: () => import('@/views/Portal.vue'),
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    children: [
      {
        path: 'dashboard',
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
        path: 'exam/students',
        name: 'exam-students',
        component: () => import('@/views/exam/Students.vue'),
      },
      {
        path: 'exam/subject-settings',
        name: 'exam-subject-settings',
        component: () => import('@/views/exam/SubjectSettings.vue'),
      },
      {
        path: 'exam/exam-number-rule',
        name: 'exam-number-rule',
        component: () => import('@/views/exam/ExamNumberRule.vue'),
      },
      {
        path: 'exam/exams',
        name: 'exam-exams',
        component: () => import('@/views/exam/Exams.vue'),
      },
      {
        path: 'exam/exams/:id',
        name: 'exam-exam-detail',
        component: () => import('@/views/exam/ExamDetail.vue'),
      },
      {
        path: 'exam/exams/:id/arrange',
        name: 'exam-exam-arrange',
        component: () => import('@/views/exam/ExamArrangement.vue'),
      },
      {
        // 阅卷与成绩录入页(KW-30~35):成绩设置、阅卷分工、成绩录入、批量导入、
        // 录入进度看板、补考成绩登记,单页内分区
        path: 'exam/exams/:id/scores',
        name: 'exam-exam-scores',
        component: () => import('@/views/exam/ExamScores.vue'),
      },
      {
        // 发布与校对锁定页(KW-36~40):发布设置、双人校对、提交与锁定、改分审批、
        // 成绩分批发布、查分与成绩异议登记,单页内分区
        path: 'exam/exams/:id/publish',
        name: 'exam-exam-publish',
        component: () => import('@/views/exam/ExamPublish.vue'),
      },
      {
        // 成绩分析页(KW-41~51):分析设置、汇总、排名、分数段、临界生、目标生、
        // 进退步、质量对比、个人趋势、等第分布、报表包导出,单页内分区
        path: 'exam/exams/:id/analysis',
        name: 'exam-exam-analysis',
        component: () => import('@/views/exam/ExamAnalysis.vue'),
      },
      {
        // 监考安排页(KW-23~29):规则与教师池、自动排监考、手工调整与替补、
        // 监考表两视图打印、巡考、考风考纪、工作量统计,单页内分区
        path: 'exam/exams/:id/invigilation',
        name: 'exam-exam-invigilation',
        component: () => import('@/views/exam/ExamInvigilation.vue'),
      },
      {
        // 通知与提醒页(KW-57~61):通知设置、四类手动发送、到期扫、录分催录、通知记录与重发,单页内分区
        path: 'exam/exams/:id/notifications',
        name: 'exam-exam-notifications',
        component: () => import('@/views/exam/ExamNotifications.vue'),
      },
      {
        // 归档与备份页(KW-65~67):一键归档、历史查询与对比、全量备份导出,单页内分区
        path: 'exam/exams/:id/archive',
        name: 'exam-exam-archive',
        component: () => import('@/views/exam/ExamArchive.vue'),
      },
      {
        // 准考证批量打印页(KW-19):一名学生一张证,不带照片
        path: 'exam/exams/:id/admission-tickets',
        name: 'exam-exam-admission-tickets',
        component: () => import('@/views/exam/ExamAdmissionTickets.vue'),
      },
      {
        // 考场名单与签到表打印页(KW-20):按考场 + 科目出表;也是编排总表
        // (KW-22)的可打印形态,浏览器“另存为 PDF”即得 PDF
        path: 'exam/exams/:id/attendance-sheets',
        name: 'exam-exam-attendance-sheets',
        component: () => import('@/views/exam/ExamAttendanceSheets.vue'),
      },
      {
        // 考场门贴与桌贴打印页(KW-21)
        path: 'exam/exams/:id/door-labels',
        name: 'exam-exam-door-labels',
        component: () => import('@/views/exam/ExamDoorLabels.vue'),
      },
      {
        // 班级成绩单打印页(KW-52):按班级出全科成绩单(班主任版,含总分与排名)
        path: 'exam/exams/:id/report-cards/class',
        name: 'exam-exam-report-class',
        component: () => import('@/views/exam/ExamReportClass.vue'),
      },
      {
        // 学生个人成绩单页(KW-53,教师/教务完整版):各科成绩、总分、含排名,可打印
        path: 'exam/exams/:id/report-cards/student',
        name: 'exam-exam-report-student',
        component: () => import('@/views/exam/ExamReportStudent.vue'),
      },
      {
        // 教师端成绩查询页(KW-54):按科目/班级/关键词检索,含成绩单设置与成绩册导出
        path: 'exam/exams/:id/teacher-scores',
        name: 'exam-exam-teacher-scores',
        component: () => import('@/views/exam/ExamTeacherScores.vue'),
      },
      {
        // 学生/家长自助查询页(KW-55):我的成绩与个人成绩单,未发布原样提示
        path: 'exam/my-scores',
        name: 'exam-my-scores',
        component: () => import('@/views/exam/ExamMyScores.vue'),
      },
      {
        // 学生/家长账号开通管理页(KW-55):一键开通、账号清单、重置口令
        path: 'exam/accounts',
        name: 'exam-exam-accounts',
        component: () => import('@/views/exam/ExamAccounts.vue'),
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
