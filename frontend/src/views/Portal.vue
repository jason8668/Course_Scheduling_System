<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { listSemesters } from '@/api/semesters'
import { getDailyBoard } from '@/api/substitutionLog'
import type { DailyBoard } from '@/api/substitutionLog'
import { publishedSemesters } from '@/api/timetables'
import type { PublicSemester } from '@/api/timetables'
import { getMyTeachingHours } from '@/api/teachingHours'
import type { TeachingHoursReport } from '@/api/teachingHours'
import { dutyNameForDate, getDutyRoster } from '@/api/duty'
import {
  getExam, getScoreProgress, listChangeRequests, listExams, listProofreading,
} from '@/api/exam'
import type { Exam, ExamDetail, ScoreProgress } from '@/api/exam'
import { mondayOf, toISODate, weekdayOf } from '@/utils/calendar'
import PortalCalendarCard from '@/components/PortalCalendarCard.vue'
import PortalAssetHints from '@/components/PortalAssetHints.vue'

const router = useRouter()
const auth = useAuthStore()
const canManage = computed(() => auth.hasRole('admin') || auth.hasRole('director'))

// 总主入口:只排已经建成的系统,新系统以后直接往网格里加一张卡,不改结构。
// 没建成的系统不画占位卡片。
// 独立页:不套 MainLayout,不带系统边栏;只留最少的账号操作(改密、退出)。

function onChangePassword() {
  router.push({ name: 'change-password' })
}

async function onLogout() {
  await auth.logout()
  router.push({ name: 'login' })
}

// ── 首页信息区:只用已有接口,不编数据;哪块接口失败就藏哪块,不拖垮整页 ──
const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
const today = new Date()
const todayISO = toISODate(today)
const todayLabel = `${today.getMonth() + 1}月${today.getDate()}日 ${WEEKDAYS[today.getDay()]}`

// 今日概览:学期 + 第几周 + 今日值日 + 今日调代课
// 迷你校历卡共用这个学期 id(总入口主页右上角);今日概览隐藏时它也照常显示。
const portalSemesterId = ref<number | null>(null)
const pubSemester = ref<PublicSemester | null>(null)
const board = ref<DailyBoard | null>(null)
const dutyName = ref<string | null>(null)
const todayReady = computed(() => pubSemester.value !== null || board.value !== null)
const pendingBoardCount = computed(() =>
  board.value ? board.value.entries.filter((e) => !e.disposed).length : 0)
const weekNumber = computed<number | null>(() => {
  const s = pubSemester.value
  if (!s) return null
  if (s.current_week_number != null) return s.current_week_number
  if (!s.start_date) return null
  const startMonday = mondayOf(new Date(`${s.start_date}T00:00:00`))
  const diff = Math.round((mondayOf(today).getTime() - startMonday.getTime()) / 86400000)
  return diff >= 0 ? Math.floor(diff / 7) + 1 : null
})

// 我的课时:只有绑定了教师主档的登录者才显示(与仪表板同口径)
const hoursMonth = ref<TeachingHoursReport | null>(null)
const hoursSemester = ref<TeachingHoursReport | null>(null)
const myMonthHours = computed(() => hoursMonth.value?.teachers[0] ?? null)
const mySemesterHours = computed(() => hoursSemester.value?.teachers[0] ?? null)
const hoursReady = computed(() => myMonthHours.value !== null || mySemesterHours.value !== null)

// 考试进行时:最近一场考试 + 录分进度 + 待办(仅管理员/教务主任看进度与待办)
const FOCUS_ORDER = ['进行中', '成绩处理中', '已发布', '已发布成绩', '草稿', '已归档']
const examsLoaded = ref(false)
const focusExam = ref<Exam | null>(null)
const focusDetail = ref<ExamDetail | null>(null)
const latestPublishedName = ref<string | null>(null)
const scoreEntered = ref<number | null>(null)
const scoreTotal = ref<number | null>(null)
const scoreSubjects = ref<{ name: string; entered: number; total: number }[]>([])
const todoProofreading = ref<number | null>(null)
const todoChangeRequests = ref<number | null>(null)

function pickFocus(exams: Exam[]): Exam | null {
  if (!exams.length) return null
  const sorted = [...exams].sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''))
  for (const s of FOCUS_ORDER) {
    const hit = sorted.find((e) => e.status === s)
    if (hit) return hit
  }
  return sorted[0]
}

// 最近场次:最近一门未考的科目;都考完了就取最后一门
const nextSession = computed(() => {
  const subjects = focusDetail.value?.subjects ?? []
  const dated = subjects.filter((s) => s.exam_date)
  if (!dated.length) return null
  const key = (s: { exam_date: string | null; start_time: string | null }) =>
    `${s.exam_date ?? ''} ${s.start_time ?? ''}`
  const upcoming = dated.filter((s) => (s.exam_date as string) >= todayISO)
    .sort((a, b) => key(a).localeCompare(key(b)))
  if (upcoming.length) return upcoming[0]
  return [...dated].sort((a, b) => key(b).localeCompare(key(a)))[0]
})
const nextSessionLabel = computed(() => {
  const s = nextSession.value
  if (!s || !s.exam_date) return '未排日程'
  const [, m, d] = s.exam_date.split('-')
  const time = s.start_time && s.end_time ? `${s.start_time}–${s.end_time}` : (s.start_time ?? '')
  const past = s.exam_date < todayISO ? '（已考）' : ''
  return `${Number(m)}月${Number(d)}日${time ? ` ${time}` : ''} · ${s.subject_name}${past}`
})

function summarizeProgress(p: ScoreProgress) {
  let entered = 0
  let total = 0
  const rows = p.subjects.map((s) => {
    const e = s.classes.reduce((a, c) => a + c.entered, 0)
    const t = s.classes.reduce((a, c) => a + c.total, 0)
    entered += e
    total += t
    return { name: s.subject_name, entered: e, total: t }
  })
  return { entered, total, rows }
}

async function load() {
  const [pubs, sems] = await Promise.all([
    publishedSemesters().catch(() => [] as PublicSemester[]),
    listSemesters().catch(() => []),
  ])
  const semesterId = sems[0]?.id ?? pubs[0]?.id ?? null
  portalSemesterId.value = semesterId
  pubSemester.value = pubs.find((p) => p.id === semesterId) ?? pubs[0] ?? null
  if (semesterId == null) {
    examsLoaded.value = true
    return
  }
  const [b, roster, hm, hs, ex] = await Promise.all([
    // 调代课筛选(Jason 2026-11-14 定):教师在首页只看跟自己有关的调代课
    // (mine=true),管理员/教务主任保持全校口径;调代课中心页本身仍是全校。
    getDailyBoard(semesterId, undefined, !canManage.value).catch(() => null),
    getDutyRoster(semesterId).catch(() => null),
    getMyTeachingHours(semesterId, 'month').catch(() => null),
    getMyTeachingHours(semesterId, 'semester').catch(() => null),
    listExams({ semesterId }).catch(() => null),
  ])
  board.value = b
  if (roster) dutyName.value = dutyNameForDate(roster, todayISO, weekdayOf(today))
  hoursMonth.value = hm
  hoursSemester.value = hs
  examsLoaded.value = true
  if (!ex) return
  const items = ex.items ?? []
  latestPublishedName.value = [...items]
    .filter((e) => e.status === '已发布成绩')
    .sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''))[0]?.name ?? null
  const focus = pickFocus(items)
  focusExam.value = focus
  if (!focus) return
  focusDetail.value = await getExam(focus.id).catch(() => null)
  if (canManage.value && (focus.status === '成绩处理中' || focus.status === '已发布成绩')) {
    const [prog, crs, prs] = await Promise.all([
      getScoreProgress(focus.id).catch(() => null),
      listChangeRequests(focus.id, '待审批').catch(() => null),
      listProofreading(focus.id).catch(() => null),
    ])
    if (prog) {
      const s = summarizeProgress(prog)
      scoreEntered.value = s.entered
      scoreTotal.value = s.total
      scoreSubjects.value = s.rows
    }
    if (crs) todoChangeRequests.value = crs.total ?? crs.items.length
    if (prs) todoProofreading.value = prs.items.filter((p) => p.status === '待校对').length
  }
}

onMounted(() => { void load() })
</script>

<template>
  <div class="ios-page portal-page">
    <div class="portal-wrap">
    <div class="portal-header">
      <span />
      <div class="portal-user">
        <span v-if="auth.user">{{ auth.user.display_name }}</span>
        <button
          type="button" class="portal-link" data-testid="portal-change-password"
          @click="onChangePassword"
        >
          修改密码
        </button>
        <button
          type="button" class="portal-link" data-testid="portal-logout"
          @click="onLogout"
        >
          退出登录
        </button>
      </div>
    </div>
    <div class="portal-hero">
      <h1 class="ios-title">智慧教务系统</h1>
      <div class="ios-subtitle">一个账号，进各个系统</div>
    </div>

    <section class="ios-section" data-testid="portal-entries">
      <div class="ios-section-title">系统入口</div>
      <div class="portal-grid">
        <div
          class="ios-card entry-card" data-testid="entry-scheduling"
          @click="router.push({ name: 'scheduling-center' })"
        >
          <div class="ios-card-body entry-body">
            <div class="entry-text">
              <div class="ios-row-title">排课系统</div>
              <div class="ios-row-sub">开学建置、配课与排课、课表查询、调课/代课、课时统计</div>
            </div>
            <span class="entry-arrow" aria-hidden="true">›</span>
          </div>
        </div>
        <div
          class="ios-card entry-card" data-testid="entry-exam"
          @click="router.push({ name: 'exam-students' })"
        >
          <div class="ios-card-body entry-body">
            <div class="entry-text">
              <div class="ios-row-title">考务成绩系统</div>
              <div class="ios-row-sub">学生档案、学科分值、考号规则、考试与成绩</div>
            </div>
            <span class="entry-arrow" aria-hidden="true">›</span>
          </div>
        </div>
        <div
          class="ios-card entry-card" data-testid="entry-asset"
          @click="router.push({ name: 'asset-workspace' })"
        >
          <div class="ios-card-body entry-body">
            <div class="entry-text">
              <div class="ios-row-title">资产管理系统</div>
              <div class="ios-row-sub">资产台账、入库验收、领用借用、盘点处置、手动同步</div>
            </div>
            <span class="entry-arrow" aria-hidden="true">›</span>
          </div>
        </div>
      </div>
    </section>

    <div class="portal-top-row" data-testid="portal-top-row">
    <section v-if="todayReady" class="ios-section" data-testid="portal-today">
      <div class="ios-section-title">今日概览</div>
      <div class="ios-card">
        <div class="ios-card-body portal-stats">
          <div class="portal-stat">
            <div class="portal-stat-label">今天</div>
            <div class="portal-stat-value">{{ todayLabel }}</div>
          </div>
          <div v-if="pubSemester" class="portal-stat">
            <div class="portal-stat-label">当前学期</div>
            <div class="portal-stat-value">{{ pubSemester.label }}</div>
          </div>
          <div v-if="weekNumber != null" class="portal-stat">
            <div class="portal-stat-label">第几周</div>
            <div class="portal-stat-value">第 {{ weekNumber }} 周</div>
          </div>
          <div v-if="dutyName" class="portal-stat">
            <div class="portal-stat-label">今日值日</div>
            <div class="portal-stat-value">{{ dutyName }}</div>
          </div>
          <div v-if="board" class="portal-stat">
            <div class="portal-stat-label">今日调代课</div>
            <div class="portal-stat-value">
              {{ board.entries.length }} 条 · 待处理 {{ pendingBoardCount }} 条
            </div>
          </div>
        </div>
        <div class="portal-card-foot">
          <router-link class="portal-btn" :to="{ name: 'substitution-center' }">查看今日调代课 →</router-link>
        </div>
      </div>
    </section>
    <PortalCalendarCard :semester-id="portalSemesterId" class="portal-calendar-col" />
    </div>

    <section v-if="hoursReady" class="ios-section" data-testid="portal-hours">
      <div class="ios-section-title">我的课时</div>
      <div class="ios-card">
        <div class="ios-card-body portal-stats">
          <div v-if="myMonthHours" class="portal-stat">
            <div class="portal-stat-label">本月已上</div>
            <div class="portal-stat-value">
              {{ myMonthHours.total }} 节
              <span class="portal-stat-sub">其中代课 {{ myMonthHours.substitute_total }} 节</span>
            </div>
          </div>
          <div v-if="mySemesterHours" class="portal-stat">
            <div class="portal-stat-label">本学期已上</div>
            <div class="portal-stat-value">
              {{ mySemesterHours.total }} 节
              <span class="portal-stat-sub">其中代课 {{ mySemesterHours.substitute_total }} 节</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <PortalAssetHints />

    <section v-if="focusExam" class="ios-section" data-testid="portal-exam">
      <div class="ios-section-title">考试进行时</div>
      <div class="ios-card">
        <div class="ios-card-body">
          <div class="portal-exam-head">
            <span class="ios-row-title">{{ focusExam.name }}</span>
            <span class="portal-tag">{{ focusExam.exam_type }} · {{ focusExam.status }}</span>
          </div>
          <div class="ios-row-sub">最近场次：{{ nextSessionLabel }}</div>
          <div v-if="latestPublishedName" class="ios-row-sub">
            最近已发布成绩：{{ latestPublishedName }}
          </div>
          <div v-if="scoreEntered !== null && scoreTotal !== null" class="portal-progress">
            <div class="portal-stat-label">录分进度</div>
            <div class="portal-stat-value">已录 {{ scoreEntered }} / 应录 {{ scoreTotal }}</div>
            <div
              v-for="row in scoreSubjects" :key="row.name"
              class="portal-progress-row"
            >
              <span>{{ row.name }}</span>
              <span>{{ row.entered }} / {{ row.total }}</span>
            </div>
          </div>
          <div
            v-if="todoProofreading !== null || todoChangeRequests !== null"
            class="ios-row-sub"
          >
            待办：<span v-if="todoProofreading !== null">待校对 {{ todoProofreading }} 项</span><span v-if="todoProofreading !== null && todoChangeRequests !== null"> · </span><span v-if="todoChangeRequests !== null">待审批改分 {{ todoChangeRequests }} 条</span>
          </div>
          <div class="portal-more">
            <router-link :to="{ name: 'exam-exam-detail', params: { id: focusExam.id } }">
              查看考试 →
            </router-link>
            <router-link
              v-if="focusExam.status === '成绩处理中'"
              :to="{ name: 'exam-exam-scores', params: { id: focusExam.id } }"
            >
              去录分 →
            </router-link>
            <router-link
              v-if="canManage && (todoProofreading !== null || todoChangeRequests !== null)"
              :to="{ name: 'exam-exam-publish', params: { id: focusExam.id } }"
            >
              去校对与发布 →
            </router-link>
          </div>
        </div>
      </div>
    </section>

    <section
      v-else-if="examsLoaded" class="ios-section"
      data-testid="portal-exam-empty"
    >
      <div class="ios-section-title">考试进行时</div>
      <div class="ios-card">
        <div class="ios-card-body portal-empty">
          <div class="ios-row-sub">本学期暂无考试</div>
          <div v-if="canManage" class="portal-empty-action">
            <router-link class="portal-btn-solid" :to="{ name: 'exam-exams' }">去新建考试 →</router-link>
          </div>
        </div>
      </div>
    </section>
    </div>
  </div>
</template>

<style scoped>
/* 总入口首页视觉(Jason 2026-11-14 定:封面要像苹果系统,每格浅蓝底、整页居中)。
   蓝色全页统一(Jason 2026-11-14:页面底与卡片深浅必须一致):页面底 #EAF3FE、
   所有卡片 #DCE9FD、里层小数据格 #EAF3FE,全部 flat、不渐变。
   只改本页:容器定宽居中 + 浅蓝卡片;其它页仍走全局左对齐版式,不动。 */
.portal-page {
  min-height: 100vh;
  padding-bottom: 0;
  background: #eaf3fe;
}
.portal-wrap { max-width: 1024px; margin: 0 auto; padding: 20px 24px 72px; }
.portal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.portal-user { display: flex; align-items: center; gap: 16px; font-size: 14px; color: #1d1d1f; }
.portal-link { background: none; border: none; padding: 0; font-size: 14px; color: #007aff; cursor: pointer; }
.portal-hero { text-align: center; margin: 28px 0 8px; }
.portal-hero .ios-title { font-size: 34px; }
.portal-hero .ios-subtitle { margin-top: 8px; font-size: 15px; }
.portal-page .ios-section { margin-top: 28px; }
.portal-page .ios-section-title { padding: 0 4px 8px; font-size: 14px; color: #5b7ba6; }
.portal-page .ios-card {
  background: #dce9fd;
  border: 1px solid rgba(0, 122, 255, 0.16);
  border-radius: 20px;
  box-shadow: 0 6px 20px rgba(0, 122, 255, 0.1);
}
.portal-page .ios-card-body { padding: 16px 20px; }
.portal-grid { display: flex; gap: 16px; flex-wrap: wrap; }
/* 今日概览 + 迷你校历卡横排:概览 flex:1 在左,校历卡固定约 320px 在右;
   窄屏自动换行上下叠。行本身顶替原来各 section 的 28px 上边距。 */
.portal-top-row { display: flex; gap: 16px; align-items: flex-start; flex-wrap: wrap; margin-top: 28px; }
.portal-page .portal-top-row .ios-section { flex: 1 1 300px; min-width: 0; margin-top: 0; }
.portal-calendar-col { flex: 0 1 320px; max-width: 100%; }
.entry-card { flex: 1; min-width: 240px; cursor: pointer; transition: transform 0.15s ease, box-shadow 0.15s ease; }
.entry-card:hover { transform: translateY(-2px); box-shadow: 0 12px 28px rgba(0, 122, 255, 0.2); }
.entry-body { display: flex; align-items: center; gap: 12px; }
.entry-text { flex: 1; min-width: 0; }
.entry-card .ios-row-title { font-size: 18px; color: #0b5ed7; }
.entry-card .ios-row-sub { color: #5b7ba6; }
.entry-arrow { flex-shrink: 0; font-size: 30px; font-weight: 300; line-height: 1; color: #007aff; }
.portal-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
.portal-stat { background: #eaf3fe; border: 1px solid rgba(0, 122, 255, 0.18); border-radius: 14px; padding: 14px 16px; }
.portal-stat-label { font-size: 13px; color: #5b7ba6; margin-bottom: 6px; }
.portal-stat-value { font-size: 17px; font-weight: 600; color: #1d1d1f; }
.portal-stat-sub { font-size: 13px; font-weight: 400; color: #5b7ba6; }
.portal-card-foot { display: flex; justify-content: flex-end; padding: 12px 20px 16px; border-top: 1px solid rgba(0, 122, 255, 0.14); }
.portal-btn { display: inline-block; background: rgba(0, 122, 255, 0.1); border: 1px solid rgba(0, 122, 255, 0.2); color: #007aff; border-radius: 999px; padding: 6px 16px; font-size: 14px; text-decoration: none; }
.portal-btn:hover { background: rgba(0, 122, 255, 0.16); }
.portal-btn-solid { display: inline-block; background: #007aff; color: #fff; border-radius: 999px; padding: 8px 22px; font-size: 14px; text-decoration: none; }
.portal-btn-solid:hover { background: #0066d6; }
.portal-more { margin-top: 14px; display: flex; gap: 12px; flex-wrap: wrap; font-size: 14px; }
.portal-more a { background: rgba(0, 122, 255, 0.1); border: 1px solid rgba(0, 122, 255, 0.2); color: #007aff; border-radius: 999px; padding: 6px 16px; text-decoration: none; }
.portal-more a:hover { background: rgba(0, 122, 255, 0.16); }
.portal-exam-head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.portal-exam-head .ios-row-title { color: #1d1d1f; }
.portal-tag { font-size: 13px; font-weight: 600; color: #007aff; background: rgba(0, 122, 255, 0.12); border-radius: 999px; padding: 2px 10px; }
.portal-progress { margin-top: 16px; }
.portal-progress-row { display: flex; justify-content: space-between; font-size: 14px; padding: 6px 0; border-top: 1px solid rgba(0, 122, 255, 0.1); }
.portal-empty { text-align: center; padding: 32px 20px; }
.portal-empty .ios-row-sub { font-size: 15px; }
.portal-empty-action { margin-top: 16px; }
</style>
