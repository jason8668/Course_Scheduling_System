<script setup lang="ts">
import { NButton, NCard, NEmpty, NSelect, NSpace, NStatistic, NTag, NText } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { listSemesters } from '@/api/semesters'
import type { SemesterListItem } from '@/api/semesters'
import { getDailyBoard } from '@/api/substitutionLog'
import type { DailyBoard } from '@/api/substitutionLog'
import { getSemesterSummary } from '@/api/wizard'
import type { SemesterSummary } from '@/api/wizard'
import { CALENDAR_EVENT_TYPE_LABELS, listCalendarEvents } from '@/api/calendar'
import type { CalendarEvent } from '@/api/calendar'
import { getMyTeacher, getPublishedTimetable, publishedSemesters } from '@/api/timetables'
import type { NamedBrief, PublicSemester, PublishedTimetable } from '@/api/timetables'
import { crossTableNote, extraRows } from '@/components/timetable/crossTable'
import TimetableGrid from '@/components/timetable/TimetableGrid.vue'
import type { GridEntry, PeriodCell } from '@/components/timetable/types'
import { addDays, eventCoversPeriod, expandCalendarEvents, mondayOf, toISODate, weekdayOf } from '@/utils/calendar'

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
const WEEKDAY_CN = ['一', '二', '三', '四', '五', '六', '日']

const router = useRouter()
const semester = ref<SemesterListItem | null>(null)
const summary = ref<SemesterSummary | null>(null)
const board = ref<DailyBoard | null>(null)
const loading = ref(true)

const boardDateLabel = computed(() =>
  board.value ? `${board.value.date}(${WEEKDAYS[board.value.weekday % 7]})` : '')
const pendingCount = computed(() =>
  board.value ? board.value.entries.filter((e) => !e.disposed).length : 0)

async function loadSummary() {
  try {
    const semesters = await listSemesters()
    if (semesters.length) {
      semester.value = semesters[0]
      ;[summary.value, board.value] = await Promise.all([
        getSemesterSummary(semesters[0].id),
        getDailyBoard(semesters[0].id).catch(() => null),
      ])
    }
  } catch {
    // 摘要是管理视角资料:纯教师帐号呼叫 listSemesters 可能 403,
    // 失败时维持原样(不显示摘要卡),不能拖垮下方的本周课表。
  } finally {
    loading.value = false
  }
}

// ── 本周课表(只靠 published 系列 + 校历 API,教师可用;独立加载) ──
const weekSemester = ref<PublicSemester | null>(null)
const weekData = ref<PublishedTimetable | null>(null)
const weekMe = ref<NamedBrief | null>(null)
const weekEvents = ref<CalendarEvent[]>([])
const weekTeacherId = ref<number | null>(null)
const weekLoading = ref(true)

const today = new Date()
const weekMonday = mondayOf(today)
const weekSunday = addDays(weekMonday, 6)
const todayWeekday = weekdayOf(today)

const weekRangeLabel = computed(() => {
  const f = (d: Date) => `${d.getMonth() + 1}月${d.getDate()}日`
  return `${f(weekMonday)}（周一）— ${f(weekSunday)}（周日）`
})

/** 周次:优先用后端 current_week_number;没有时按 start_date 的周一推算。 */
const weekNumber = computed<number | null>(() => {
  const s = weekSemester.value
  if (!s) return null
  if (s.current_week_number != null) return s.current_week_number
  if (!s.start_date) return null
  const startMonday = mondayOf(new Date(`${s.start_date}T00:00:00`))
  const diff = Math.round((weekMonday.getTime() - startMonday.getTime()) / 86400000)
  return diff >= 0 ? Math.floor(diff / 7) + 1 : null
})
const weekParity = computed<'odd' | 'even' | null>(() => {
  const s = weekSemester.value
  if (s?.current_week_parity) return s.current_week_parity
  if (weekNumber.value == null) return null
  return weekNumber.value % 2 === 1 ? 'odd' : 'even'
})
const weekTitle = computed(() => {
  const s = weekSemester.value
  if (!s?.start_date || weekNumber.value == null) return '本周课表'
  const parity = weekParity.value === 'odd' ? '（单周）' : weekParity.value === 'even' ? '（双周）' : ''
  return `本周课表 · 第 ${weekNumber.value} 周${parity}`
})
const noStartDate = computed(() => !!weekSemester.value && !weekSemester.value.start_date)

const weekTeacherOptions = computed(() =>
  (weekData.value?.teachers ?? []).map((t) => ({ label: t.name, value: t.id })))
const effectiveTeacherId = computed(() => weekMe.value?.id ?? weekTeacherId.value)

const defaultWeekTable = computed(() => {
  const ts = weekData.value?.period_tables ?? []
  return ts.find((t) => t.is_default) ?? ts[0] ?? null
})
const numWeekdays = computed(() => defaultWeekTable.value?.num_weekdays ?? 5)
const highlightWeekday = computed<number | null>(() =>
  todayWeekday <= numWeekdays.value ? todayWeekday : null)

/** 教师过滤 + 单双周过滤后的原始条目。 */
const weekRawEntries = computed(() => {
  const all = weekData.value?.entries ?? []
  const tid = effectiveTeacherId.value
  if (tid == null) return []
  const parity = weekParity.value
  return all.filter((e) => {
    if (!e.teacher_ids.includes(tid)) return false
    if (parity === 'odd') return !e.week_parity || e.week_parity === 'odd'
    if (parity === 'even') return !e.week_parity || e.week_parity === 'even'
    return true
  })
})

const weekPeriods = computed<PeriodCell[]>(() => {
  const base = (defaultWeekTable.value?.periods ?? []) as PeriodCell[]
  return [...base, ...extraRows(
    weekRawEntries.value, weekData.value?.classes ?? [],
    weekData.value?.period_tables ?? [], defaultWeekTable.value,
  ) as PeriodCell[]]
})

/**
 * 整形 + 校历覆盖:活动整形成 GridEntry 注入;被活动覆盖的课剔除并计数。
 * 全天活动只在当天第一个 regular 节次放一条(其余格留空,避免 span 跨休息节次错位)。
 */
const weekShaped = computed(() => {
  const base: GridEntry[] = weekRawEntries.value.map((e) => ({
    id: e.id, weekday: e.weekday, period_no: e.period_no, span: e.span, locked: false,
    subject: e.subject,
    teacher: e.classes.join('、'),
    room: e.room ?? undefined,
    note: crossTableNote(e, weekData.value?.classes ?? [], weekData.value?.period_tables ?? [], defaultWeekTable.value),
    week: e.week_parity === 'odd' ? '单' as const : e.week_parity === 'even' ? '双' as const : undefined,
  }))
  const expanded = expandCalendarEvents(weekEvents.value, toISODate(weekMonday), toISODate(weekSunday))
  if (!expanded.size) return { entries: base, affected: [] as GridEntry[] }

  const removed = new Set<number | string>()
  const affected: GridEntry[] = []
  const calendarEntries: GridEntry[] = []
  const regularNos = (w: number) =>
    weekPeriods.value.filter((p) => p.weekday === w && p.type === 'regular').map((p) => p.period_no)

  for (let w = 1; w <= 7; w++) {
    const iso = toISODate(addDays(weekMonday, w - 1))
    const dayEvents = expanded.get(iso) ?? []
    for (const ev of dayEvents) {
      const fullDay = ev.period_start === null || ev.period_end === null
      const covered = fullDay
        ? regularNos(w)
        : Array.from(
          { length: Math.max(0, (ev.period_end ?? 0) - (ev.period_start ?? 0) + 1) },
          (_, i) => (ev.period_start ?? 0) + i,
        )
      for (const entry of base) {
        if (entry.weekday !== w || removed.has(entry.id)) continue
        const spanEnd = entry.period_no + (entry.span ?? 1) - 1
        const overlaps = covered.some((no) => no >= entry.period_no && no <= spanEnd)
          || (fullDay && eventCoversPeriod(ev, entry.period_no))
        if (overlaps) {
          removed.add(entry.id)
          affected.push(entry)
        }
      }
      const firstPeriod = fullDay ? covered[0] : ev.period_start
      if (firstPeriod != null) {
        calendarEntries.push({
          id: `cal-${ev.id}-${w}`,
          weekday: w,
          period_no: firstPeriod,
          subject: ev.title,
          teacher: '校历活动',
          note: fullDay
            ? `全天活动 · ${CALENDAR_EVENT_TYPE_LABELS[ev.event_type]}`
            : CALENDAR_EVENT_TYPE_LABELS[ev.event_type],
          tone: 'calendar',
        })
      }
    }
  }
  return {
    entries: [...base.filter((e) => !removed.has(e.id)), ...calendarEntries],
    affected,
  }
})
const weekEntries = computed(() => weekShaped.value.entries)
const weekAffected = computed(() => weekShaped.value.affected)

async function loadWeek() {
  try {
    const semesters = await publishedSemesters()
    if (!semesters.length) return
    weekSemester.value = semesters[0]
    const sid = semesters[0].id
    const [data, me, events] = await Promise.all([
      getPublishedTimetable(sid),
      getMyTeacher(sid).catch(() => null),
      listCalendarEvents(sid, toISODate(weekMonday), toISODate(weekSunday)).catch(() => [] as CalendarEvent[]),
    ])
    weekData.value = data
    weekMe.value = me
    weekEvents.value = events
    weekTeacherId.value = me?.id ?? data?.teachers[0]?.id ?? null
  } catch {
    // 本周课表加载失败只让本卡显示空状态,不影响整个仪表板
    weekData.value = null
  } finally {
    weekLoading.value = false
  }
}

onMounted(() => {
  void loadSummary()
  void loadWeek()
})
</script>

<template>
  <n-space vertical size="large">
    <h1 style="margin: 0">仪表板</h1>

    <n-card data-testid="dash-week" :title="weekTitle">
      <template #header-extra>
        <n-text depth="3" style="font-size: 13px">{{ weekRangeLabel }}</n-text>
      </template>
      <n-space v-if="!weekLoading && weekData" vertical>
        <n-text v-if="noStartDate" type="warning" style="font-size: 13px">
          学期未设定开始日期，无法计算周次
        </n-text>
        <n-space align="center" :wrap="true">
          <n-text depth="3" style="font-size: 13px">{{ weekRangeLabel }}</n-text>
          <n-select
            v-if="!weekMe" v-model:value="weekTeacherId" data-testid="dash-week-teacher"
            :options="weekTeacherOptions" style="width: 160px" filterable
            placeholder="选择教师"
          />
          <n-tag v-else size="small" type="info">本人课表</n-tag>
        </n-space>
        <n-empty v-if="weekPeriods.length === 0" description="此学期尚无节次表" />
        <TimetableGrid
          v-else
          :periods="weekPeriods" :num-weekdays="numWeekdays" :entries="weekEntries"
          :highlight-weekday="highlightWeekday" readonly
        />
        <n-text v-if="weekAffected.length" depth="3" style="font-size: 12px">
          校历活动占用：{{ weekAffected.length }} 节课受影响（{{
            weekAffected.map((e) => `周${WEEKDAY_CN[e.weekday - 1]}第${e.period_no}节 ${e.subject}`).join('、')
          }}）
        </n-text>
      </n-space>
      <n-empty
        v-else-if="!weekLoading" description="本周课表：尚无已发布的课表"
        data-testid="dash-week-none"
      />
      <n-text v-else depth="3">加载中…</n-text>
    </n-card>

    <n-card v-if="semester" :title="`${semester.label} · 资料摘要`">
      <div class="stat-blocks">
        <div class="stat-block" style="--stat-bg: #eef6f8; --stat-fg: #0d5a6e">
          <div class="stat-value">{{ summary?.subjects ?? 0 }}</div>
          <div class="stat-label">科目</div>
        </div>
        <div class="stat-block" style="--stat-bg: #eef3fb; --stat-fg: #2b6cb0">
          <div class="stat-value">{{ summary?.teachers ?? 0 }}</div>
          <div class="stat-label">教师</div>
        </div>
        <div class="stat-block" style="--stat-bg: #edf7f0; --stat-fg: #2f855a">
          <div class="stat-value">{{ summary?.classes ?? 0 }}</div>
          <div class="stat-label">班级</div>
        </div>
        <div class="stat-block" style="--stat-bg: #fdf3e7; --stat-fg: #c05621">
          <div class="stat-value">{{ summary?.rooms ?? 0 }}</div>
          <div class="stat-label">场地</div>
        </div>
      </div>
    </n-card>

    <n-card v-else-if="!loading">
      <n-empty description="尚未建立任何学期资料">
        <template #extra>
          <n-button type="primary" @click="router.push({ name: 'wizard' })">
            前往设置精灵
          </n-button>
        </template>
      </n-empty>
    </n-card>

    <n-card v-if="semester && board" data-testid="dash-today" :title="`今日调代课 · ${boardDateLabel}`">
      <n-space v-if="board.entries.length" vertical>
        <n-space align="center">
          <n-statistic label="今日异动" :value="board.entries.length" />
          <n-tag v-if="pendingCount" type="warning" data-testid="dash-pending">
            尚有 {{ pendingCount }} 节待安排
          </n-tag>
          <n-tag v-else type="success">今日皆已安排</n-tag>
        </n-space>
        <div>
          <n-button type="primary" @click="router.push({ name: 'daily-board' })">
            查看今日看板
          </n-button>
        </div>
      </n-space>
      <n-empty v-else description="今日无调代课" data-testid="dash-noboard" />
    </n-card>
  </n-space>
</template>

<style scoped>
.stat-blocks { display: flex; flex-wrap: wrap; gap: 16px; }
.stat-block {
  min-width: 128px; flex: 1; max-width: 200px;
  background: var(--stat-bg); border-radius: 12px; padding: 16px 18px;
}
.stat-value { font-size: 28px; font-weight: 700; line-height: 1.2; color: var(--stat-fg); }
.stat-label { margin-top: 4px; font-size: 13px; color: var(--stat-fg); opacity: 0.85; }
</style>
