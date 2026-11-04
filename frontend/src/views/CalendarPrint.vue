<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { listCalendarEvents } from '@/api/calendar'
import type { CalendarEvent, CalendarEventType } from '@/api/calendar'
import { publishedSemesters } from '@/api/timetables'
import type { PublicSemester } from '@/api/timetables'
import { getSchoolSettings } from '@/api/assignments'
import {
  monthsInRange, monthWeeks, resolveSemesterEnd, weekLabel,
} from '@/utils/calendarList'
import { autoMarkerKind, expandCalendarEvents } from '@/utils/calendar'

// 校历打印页:独立一页供 A4 打印张贴,不套侧边栏(仿 TimetablePrint.vue 模式)。
// 只印日期上的校历:按月的日历框,活动标题在日期格里;下面的按月明细表已拿掉
// (Jason 2026-11-04 定:打印只要校历,不要下面每个日期的明细记录)。

const route = useRoute()

// 活动类型颜色（与主页面 TYPE_COLORS 一致）：整格高亮用底色，描边用前景色。
const PRINT_COLORS: Record<CalendarEventType, { bg: string; fg: string }> = {
  holiday: { bg: '#fdecea', fg: '#c0392b' },
  activity: { bg: '#eef6f8', fg: '#0d5a6e' },
  exam: { bg: '#fdf3e7', fg: '#c05621' },
  other: { bg: '#eef3fb', fg: '#2b6cb0' },
}

// 有活动日期整格按颜色高亮:取第一个非小标记事件(传统节日/节气是小字,
// 不抢整格底色);国家假日走放假红块,调休补课日走琥珀块;打印页没有今天标记。
const WORKDAY_PRINT_COLORS = { bg: '#fff8e1', fg: '#bf6900' }
function cellStyle(cell: { events: CalendarEvent[] }) {
  const ev = cell.events.find((e) => autoMarkerKind(e) !== 'small')
  if (!ev) return {}
  const c = autoMarkerKind(ev) === 'workday' ? WORKDAY_PRINT_COLORS : PRINT_COLORS[ev.event_type]
  return { background: c.bg, outline: `2px solid ${c.fg}`, outlineOffset: '-2px' }
}
// 格里每条活动:小标记只留弱色小字;调休琥珀字;其余走类型颜色。
function evClass(ev: CalendarEvent) {
  return autoMarkerKind(ev) === 'small' ? 'f-mark' : 'f-ev'
}
function evStyle(ev: CalendarEvent) {
  if (autoMarkerKind(ev) === 'small') return {}
  const c = autoMarkerKind(ev) === 'workday' ? WORKDAY_PRINT_COLORS : PRINT_COLORS[ev.event_type]
  return { color: c.fg }
}

const semester = ref<PublicSemester | null>(null)
const events = ref<CalendarEvent[]>([])
const schoolName = ref('')
const loading = ref(true)
const printedAt = new Date().toLocaleString('zh-CN', { hour12: false })

const sid = computed(() => Number(route.query.semester_id) || null)

// ── 学期日历（月框）：与主页面一致，从开学第一天到最后一天 ──
const WEEKDAY_HEADS = ['一', '二', '三', '四', '五', '六', '日']
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
    // 打印页不标今天：今天标记只在浏览时出现，打印出来不带。
    isToday: false,
    // 活动只在本月框内显示：跨月补齐格里的同一天不再重复出现活动。
    events: cell.inMonth ? (expandedByDate.value.get(cell.iso) ?? []) : [],
  }))),
})))
const semesterRange = computed(() => {
  const s = semester.value
  if (!s) return ''
  if (s.start_date && s.end_date) return `${s.start_date} 至 ${s.end_date}`
  return s.start_date ?? s.end_date ?? ''
})

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
                  :class="{ 'is-out': !cell.inRange }"
                  :style="cellStyle(cell)"
                >
                  <div class="f-day">{{ cell.dayNum }}</div>
                  <div
                    v-for="ev in cell.events" :key="ev.id" :class="evClass(ev)"
                    :style="evStyle(ev)"
                  >{{ ev.title }}</div>
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

      <p class="foot">
        说明：红色块为国家假日，琥珀色为调休补课日，小字为传统节日 / 二十四节气。周次按学期开始日期计算，开学所在周为第 1 周，周一起算。
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
.weekno-col { width: 52px; text-align: center; }
.frame-grid td.weekno-col { background: #f4f4f4; font-size: 12px; vertical-align: middle; }
.cal-frames { margin-bottom: 18px; }
.month-frame { margin-bottom: 16px; }
.month-frame-title { font-size: 16px; font-weight: 700; margin: 0 0 6px; padding-left: 8px; border-left: 4px solid #000; }
.frame-grid { border-collapse: collapse; width: 100%; table-layout: fixed; font-size: 12px; }
.frame-grid th, .frame-grid td { border: 1px solid #000; padding: 4px 5px; text-align: left; vertical-align: top; }
.frame-grid th { background: #eee; text-align: center; font-size: 13px; }
.frame-grid td { height: 52px; }
.frame-grid td.is-out { color: #999; }
.f-day { font-weight: 700; font-size: 13px; margin-bottom: 2px; }
.f-ev { font-size: 11px; line-height: 1.4; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
/* 传统节日 / 二十四节气的小标记:弱色小字,无底色。 */
.f-mark { font-size: 10px; line-height: 1.4; color: #888; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.foot { font-size: 12px; color: #444; margin-top: 16px; }
.empty { text-align: center; padding: 40px 0; font-size: 15px; }

@media print {
  @page { size: A4 portrait; margin: 12mm; }
  /* 打印时保留活动格底色（浏览器默认会去掉背景色）。 */
  .frame-grid td { print-color-adjust: exact; -webkit-print-color-adjust: exact; }
  .no-print { display: none !important; }
  .sheet { max-width: none; padding: 0; }
  .month-frame { page-break-inside: avoid; }
}
</style>
