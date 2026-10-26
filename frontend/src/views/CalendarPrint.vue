<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  CALENDAR_EVENT_TYPE_LABELS, listCalendarEvents,
} from '@/api/calendar'
import type { CalendarEvent, CalendarEventType } from '@/api/calendar'
import { getPublishedTimetable, publishedSemesters } from '@/api/timetables'
import type { PublicClass, PublicSemester } from '@/api/timetables'
import { getSchoolSettings } from '@/api/assignments'
import {
  eventDateText, eventWeekText, groupEventsByMonth, monthsInRange, monthWeeks,
  resolveSemesterEnd, weekdayLabel, weekLabel,
} from '@/utils/calendarList'
import { expandCalendarEvents, toISODate } from '@/utils/calendar'
import { classLabel } from '@/utils/labels'

// 校历打印页:独立一页供 A4 打印张贴,不套侧边栏(仿 TimetablePrint.vue 模式)。
// 内容与校历主页面一致:本学期全部活动按月分组,一页内完整列出。

const route = useRoute()
const semester = ref<PublicSemester | null>(null)
const classes = ref<PublicClass[]>([])
const events = ref<CalendarEvent[]>([])
const schoolName = ref('')
const loading = ref(true)
const printedAt = new Date().toLocaleString('zh-CN', { hour12: false })

const sid = computed(() => Number(route.query.semester_id) || null)
const monthGroups = computed(() => groupEventsByMonth(events.value))

// ── 学期日历（月框）：与主页面一致，从开学第一天到最后一天 ──
const WEEKDAY_HEADS = ['一', '二', '三', '四', '五', '六', '日']
const todayIso = toISODate(new Date())
const rangeStart = computed(() => semester.value?.start_date ?? null)
const rangeEnd = computed(() =>
  resolveSemesterEnd(semester.value?.start_date ?? null, semester.value?.end_date ?? null))
const semesterMonths = computed(() =>
  rangeStart.value && rangeEnd.value ? monthsInRange(rangeStart.value, rangeEnd.value) : [])
const expandedByDate = computed(() =>
  rangeStart.value && rangeEnd.value
    ? expandCalendarEvents(events.value, rangeStart.value, rangeEnd.value)
    : new Map<string, CalendarEvent[]>())
const monthFrames = computed(() => semesterMonths.value.map((m) => ({
  ...m,
  weeks: monthWeeks(m.year, m.month).map((week) => week.map((cell) => ({
    ...cell,
    inRange: rangeStart.value! <= cell.iso && cell.iso <= rangeEnd.value!,
    isToday: cell.iso === todayIso,
    events: expandedByDate.value.get(cell.iso) ?? [],
  }))),
})))
const semesterRange = computed(() => {
  const s = semester.value
  if (!s) return ''
  if (s.start_date && s.end_date) return `${s.start_date} 至 ${s.end_date}`
  return s.start_date ?? s.end_date ?? ''
})

function scopeText(ev: CalendarEvent): string {
  if (ev.scope_type === 'school') return '全校'
  if (ev.scope_type === 'grade') return ev.scope_id != null ? `${ev.scope_id}年级` : '年级'
  const c = classes.value.find((x) => x.id === ev.scope_id)
  return c ? classLabel(c) : (ev.scope_id != null ? `班级 ${ev.scope_id}` : '班级')
}
function timeText(ev: CalendarEvent): string {
  if (ev.period_start === null || ev.period_end === null) return '全天'
  return `第 ${ev.period_start}–${ev.period_end} 节`
}

function doPrint() {
  window.print()
}
function doClose() {
  window.close()
}

onMounted(async () => {
  if (sid.value === null) {
    loading.value = false
    return
  }
  try {
    const semesters = await publishedSemesters()
    semester.value = semesters.find((s) => s.id === sid.value) ?? null
  } catch {
    semester.value = null
  }
  try {
    // 不传范围:一次拉取本学期全部活动,与主页面一致。
    events.value = await listCalendarEvents(sid.value)
  } catch {
    events.value = []
  }
  try {
    const data = await getPublishedTimetable(sid.value)
    classes.value = data?.classes ?? []
  } catch {
    classes.value = []
  }
  // 校名接口仅管理员可读;读不到就不显示校名,不影响其余内容
  try {
    schoolName.value = (await getSchoolSettings()).school_name
  } catch {
    schoolName.value = ''
  }
  loading.value = false
})
</script>

<template>
  <div class="sheet">
    <div class="no-print toolbar">
      <button type="button" data-testid="cal-print-btn" @click="doPrint">打印</button>
      <button type="button" @click="doClose">关闭</button>
    </div>

    <template v-if="semester">
      <header class="head">
        <h1 v-if="schoolName" class="school">{{ schoolName }}</h1>
        <h2 class="title">学校校历</h2>
        <div class="meta">
          <span>{{ semester.label }}<span v-if="semesterRange"> · {{ semesterRange }}</span></span>
          <span class="printed">打印时间:{{ printedAt }}</span>
        </div>
      </header>

      <p class="summary">共 {{ events.length }} 条活动</p>

      <div v-if="semesterMonths.length" class="cal-frames">
        <div v-for="frame in monthFrames" :key="`${frame.year}-${frame.month}`" class="month-frame">
          <h3 class="month-frame-title">{{ frame.label }}</h3>
          <table class="frame-grid">
            <thead>
              <tr><th class="weekno-col">周次</th><th v-for="h in WEEKDAY_HEADS" :key="h">周{{ h }}</th></tr>
            </thead>
            <tbody>
              <tr v-for="(week, wi) in frame.weeks" :key="wi">
                <td class="weekno-col">{{ weekLabel(rangeStart, week[0]!.iso) }}</td>
                <td
                  v-for="cell in week" :key="cell.iso"
                  :class="{ 'is-out': !cell.inRange, 'is-today': cell.isToday }"
                >
                  <div class="f-day">{{ cell.dayNum }}</div>
                  <div v-for="ev in cell.events" :key="ev.id" class="f-ev">{{ ev.title }}</div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <p v-else-if="!semester.start_date" class="empty">
        本学期尚未设定开始日期，无法生成整学期日历；请至「学期与节次表」补上开始/结束日期。
      </p>

      <p v-if="!events.length" class="empty">本学期暂无校历活动。</p>

      <div v-for="group in monthGroups" :key="group.month" class="month-group">
        <h3 class="month-title">{{ group.month }}</h3>
        <table class="grid" data-testid="cal-print-table">
          <thead>
            <tr>
              <th class="date-col">日期</th>
              <th class="weekno-col">周次</th>
              <th class="week-col">星期</th>
              <th>名称</th>
              <th>类型</th>
              <th>范围</th>
              <th>时间</th>
              <th>备注</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="ev in group.events" :key="ev.id">
              <td class="date-col">{{ eventDateText(ev) }}</td>
              <td class="weekno-col">{{ eventWeekText(rangeStart, ev) }}</td>
              <td class="week-col">{{ weekdayLabel(ev.start_date) }}</td>
              <td><strong>{{ ev.title }}</strong></td>
              <td>
                {{ CALENDAR_EVENT_TYPE_LABELS[ev.event_type as CalendarEventType] }}
                <span v-if="ev.weekly_recurring">（每周重复）</span>
              </td>
              <td>{{ scopeText(ev) }}</td>
              <td>{{ timeText(ev) }}</td>
              <td>{{ ev.note ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <p class="foot">
        说明：类型包括放假停课、全校活动、考试、其他；「每周重复」表示该活动在起止日期内每周同一天重复发生。周次按学期开始日期计算，开学所在周为第 1 周，周一起算。
      </p>
    </template>

    <p v-else-if="loading" class="empty">载入中…</p>
    <p v-else class="empty">未指定学期,或该学期不存在。</p>
  </div>
</template>

<style scoped>
.sheet {
  max-width: 820px;
  margin: 0 auto;
  padding: 24px;
  color: #000;
  background: #fff;
  font-family: "Microsoft YaHei", "Microsoft JhengHei", "PingFang SC", "PingFang TC", sans-serif;
}
.toolbar { display: flex; gap: 8px; justify-content: flex-end; margin-bottom: 16px; }
.toolbar button {
  padding: 6px 16px; cursor: pointer; border: 1px solid #888; border-radius: 4px; background: #f4f4f4;
}
.head { text-align: center; margin-bottom: 14px; }
.school { font-size: 22px; margin: 0 0 4px; }
.title { font-size: 19px; font-weight: 600; letter-spacing: 2px; margin: 0 0 8px; }
.meta { display: flex; justify-content: space-between; font-size: 13px; padding: 0 4px; }
.printed { color: #444; }
.summary { font-size: 13px; margin: 0 0 14px; padding: 0 4px; }
.month-group { margin-bottom: 18px; }
.month-title { font-size: 16px; font-weight: 700; margin: 0 0 8px; padding-left: 8px; border-left: 4px solid #000; }
.grid { border-collapse: collapse; width: 100%; table-layout: fixed; font-size: 13px; }
.grid th, .grid td { border: 1px solid #000; padding: 5px 6px; text-align: left; vertical-align: middle; }
.grid th { background: #eee; font-size: 14px; }
.date-col { width: 150px; }
.weekno-col { width: 52px; text-align: center; }
.frame-grid td.weekno-col { background: #f4f4f4; font-size: 12px; vertical-align: middle; }
.week-col { width: 56px; }
.cal-frames { margin-bottom: 18px; }
.month-frame { margin-bottom: 16px; }
.month-frame-title { font-size: 16px; font-weight: 700; margin: 0 0 6px; padding-left: 8px; border-left: 4px solid #000; }
.frame-grid { border-collapse: collapse; width: 100%; table-layout: fixed; font-size: 12px; }
.frame-grid th, .frame-grid td { border: 1px solid #000; padding: 4px 5px; text-align: left; vertical-align: top; }
.frame-grid th { background: #eee; text-align: center; font-size: 13px; }
.frame-grid td { height: 52px; }
.frame-grid td.is-out { color: #999; }
.frame-grid td.is-today { outline: 2px solid #000; outline-offset: -2px; }
.f-day { font-weight: 700; font-size: 13px; margin-bottom: 2px; }
.f-ev { font-size: 11px; line-height: 1.4; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.foot { font-size: 12px; color: #444; margin-top: 16px; }
.empty { text-align: center; padding: 40px 0; font-size: 15px; }

@media print {
  @page { size: A4 portrait; margin: 12mm; }
  .no-print { display: none !important; }
  .sheet { max-width: none; padding: 0; }
  .month-group { page-break-inside: avoid; }
  .month-frame { page-break-inside: avoid; }
}
</style>
