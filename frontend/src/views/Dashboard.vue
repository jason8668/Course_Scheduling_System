<script setup lang="ts">
import { NAlert, NButton, NEmpty, NSelect, NSpace, NStatistic, NTag, NText } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { listSemesters } from '@/api/semesters'
import type { SemesterListItem } from '@/api/semesters'
import { getDailyBoard } from '@/api/substitutionLog'
import type { DailyBoard } from '@/api/substitutionLog'
import { getSemesterSummary } from '@/api/wizard'
import type { SemesterSummary } from '@/api/wizard'
import { CALENDAR_EVENT_TYPE_LABELS, listCalendarEvents, listWorkdays } from '@/api/calendar'
import type { CalendarEvent, Workday } from '@/api/calendar'
import {
  getActualTimetable, getMyTeacher, getPublishedTimetable, publishedSemesters,
} from '@/api/timetables'
import type {
  ActualDay, NamedBrief, PublicSemester, PublishedTimetable,
} from '@/api/timetables'
import { getMyTeachingHours } from '@/api/teachingHours'
import type { TeachingHoursReport } from '@/api/teachingHours'
import { dutyNameForDate, getDutyRoster } from '@/api/duty'
import type { DutyRoster } from '@/api/duty'
import { crossTableNote, extraRows } from '@/components/timetable/crossTable'
import NotificationWidget from '@/components/teacher/NotificationWidget.vue'
import TeacherHomeSections from '@/components/teacher/TeacherHomeSections.vue'
import TimetableGrid from '@/components/timetable/TimetableGrid.vue'
import { useAuthStore } from '@/stores/auth'
import type { GridEntry, PeriodCell } from '@/components/timetable/types'
import { addDays, eventCoversPeriod, expandCalendarEvents, mondayOf, toISODate, weekdayOf } from '@/utils/calendar'

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
const WEEKDAY_CN = ['一', '二', '三', '四', '五', '六', '日']

const router = useRouter()
const auth = useAuthStore()
const canManage = computed(() =>
  auth.hasRole('admin') || auth.hasRole('director'))
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
const weekDuty = ref<DutyRoster | null>(null)
const weekTeacherId = ref<number | null>(null)
const weekLoading = ref(true)

// 教师本人已上课时数(本月 / 本学期):只有绑定了教师主档的登录者才显示
const hoursMonth = ref<TeachingHoursReport | null>(null)
const hoursSemester = ref<TeachingHoursReport | null>(null)

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
const weekDutyText = computed(() => {
  if (!weekDuty.value) return ''
  const parts: string[] = []
  for (let w = 1; w <= numWeekdays.value; w++) {
    const dateStr = toISODate(addDays(weekMonday, w - 1))
    const name = dutyNameForDate(weekDuty.value, dateStr, w)
    if (name) parts.push(`周${WEEKDAY_CN[w - 1]} ${name}`)
  }
  return parts.join(' · ')
})
const weekAffected = computed(() => weekShaped.value.affected)

const pendingWorkdays = ref<Workday[]>([])
const actualWeek = ref<ActualDay[]>([])
const weekWorkdays = computed(() => actualWeek.value.filter((d) => d.workday_title))
function weekWorkdaySlots(day: ActualDay) {
  const tid = effectiveTeacherId.value
  if (tid == null) return day.slots
  return day.slots.filter((s) => s.teacher_ids.includes(tid))
}

async function loadWeek() {
  try {
    const semesters = await publishedSemesters()
    if (!semesters.length) return
    weekSemester.value = semesters[0]
    const sid = semesters[0].id
    const todayStr = toISODate(new Date())
    const in14Str = toISODate(addDays(new Date(), 14))
    const [data, me, events, duty, wds, actual] = await Promise.all([
      getPublishedTimetable(sid),
      getMyTeacher(sid).catch(() => null),
      listCalendarEvents(sid, toISODate(weekMonday), toISODate(weekSunday)).catch(() => [] as CalendarEvent[]),
      getDutyRoster(sid).catch(() => null),
      listWorkdays(sid, todayStr, in14Str).catch(() => [] as Workday[]),
      getActualTimetable(sid, toISODate(weekMonday), toISODate(weekSunday)).catch(() => [] as ActualDay[]),
    ])
    pendingWorkdays.value = wds.filter((w) => !w.has_copy)
    actualWeek.value = actual
    weekData.value = data
    weekMe.value = me
    weekEvents.value = events
    weekDuty.value = duty
    weekTeacherId.value = me?.id ?? data?.teachers[0]?.id ?? null
    // 教师本人的课时卡:本月 + 本学期已上课时数;失败时整卡隐藏,不拖垮仪表板
    if (me) {
      try {
        const [m, s] = await Promise.all([
          getMyTeachingHours(sid, 'month'),
          getMyTeachingHours(sid, 'semester'),
        ])
        hoursMonth.value = m
        hoursSemester.value = s
      } catch {
        hoursMonth.value = null
        hoursSemester.value = null
      }
    }
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
  <div class="ios-page">
    <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap">
      <div>
        <h1 class="ios-title">仪表板</h1>
        <div v-if="weekMe && weekSemester" class="ios-subtitle">
          {{ weekMe.name }} · {{ weekSemester.label }}
        </div>
      </div>
      <!-- 通知放仪表板右上角小框,点开看全部;只给绑定教师档案的人显示。 -->
      <NotificationWidget v-if="weekMe && weekSemester" :semester-id="weekSemester.id" />
    </div>

    <section
      v-if="weekMe && (hoursMonth || hoursSemester)"
      class="ios-section" data-testid="dash-hours"
    >
      <div class="ios-section-title">我的课时</div>
      <div class="ios-card">
        <div class="ios-card-body">
      <n-space align="center">
        <div v-if="hoursMonth">
          <n-statistic
            label="本月已上课时数"
            :value="hoursMonth.teachers[0]?.total ?? 0"
          />
          <n-text depth="3" style="font-size: 13px">其中代课 {{ hoursMonth.teachers[0]?.substitute_total ?? 0 }} 节</n-text>
        </div>
        <div v-if="hoursSemester">
          <n-statistic
            label="本学期已上课时数"
            :value="hoursSemester.teachers[0]?.total ?? 0"
          />
          <n-text depth="3" style="font-size: 13px">其中代课 {{ hoursSemester.teachers[0]?.substitute_total ?? 0 }} 节</n-text>
        </div>
        <n-text depth="3" style="font-size: 13px">统计至今天（未来日期不计入已上课时）</n-text>
      </n-space>
        </div>
      </div>
    </section>

    <section class="ios-section" data-testid="dash-week">
      <div class="ios-section-title"><span>{{ weekTitle }}</span><span style="font-size: 13px; font-weight: 400">{{ weekRangeLabel }}</span></div>
      <div class="ios-card">
        <div class="ios-card-body">
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
        <!-- 同课表查询页:值日行一直画,没排轮值时明写尚未安排,不藏整行。 -->
        <n-text depth="3" style="font-size: 13px" data-testid="dash-duty">
          行政值日: {{ weekDutyText || '尚未安排（请管理员在系统管理页排每周轮值）' }}
        </n-text>
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
        </div>
      </div>
    </section>

    <section v-if="semester" class="ios-section">
      <div class="ios-section-title">{{ semester.label }} · 资料摘要</div>
      <div class="ios-card">
        <div class="ios-card-body">
      <div class="stat-blocks">
        <div class="stat-block" style="--stat-bg: #eaf3ff; --stat-fg: #007aff">
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
        </div>
      </div>
    </section>

    <section v-else-if="!loading && canManage" class="ios-section">
      <div class="ios-card">
        <div class="ios-card-body">
      <n-empty description="尚未建立任何学期资料">
        <template #extra>
          <n-button type="primary" @click="router.push({ name: 'wizard' })">
            前往设置精灵
          </n-button>
        </template>
      </n-empty>
        </div>
      </div>
    </section>

    <section v-if="canManage && pendingWorkdays.length" class="ios-section" data-testid="dash-workdays">
      <div class="ios-section-title">调休日待复制课表</div>
      <div class="ios-card">
        <div class="ios-card-body">
          <n-alert type="warning" style="margin-bottom: 8px">
            {{ pendingWorkdays.length }} 个调休上班日在 14 天内还没复制课表,实际课表那天会是空的。
          </n-alert>
          <div v-for="w in pendingWorkdays" :key="w.date" class="ios-row">
            <div class="ios-row-main">
              <div class="ios-row-title">{{ w.date }} {{ w.title }}</div>
            </div>
          </div>
          <n-button type="primary" @click="router.push({ name: 'scheduling-center' })">
            去排课中心复制
          </n-button>
        </div>
      </div>
    </section>

    <section v-if="weekWorkdays.length" class="ios-section" data-testid="dash-week-workdays">
      <div class="ios-section-title">本周调休日实际课表</div>
      <div class="ios-card">
        <div class="ios-card-body">
          <div v-for="d in weekWorkdays" :key="d.date">
            <div class="ios-row-title" style="margin-top: 8px">
              {{ d.date }} {{ d.workday_title }}
              <n-tag v-if="d.workday_pending" type="warning" size="small">尚未复制课表</n-tag>
            </div>
            <n-empty v-if="!weekWorkdaySlots(d).length" description="这天没有你的课" />
            <div v-for="s in weekWorkdaySlots(d)" :key="`${s.class_unit_id}-${s.period_no}`" class="ios-row">
              <div class="ios-row-main">
                <div class="ios-row-title">
                  第{{ s.period_no }}节 {{ s.subject }} · {{ s.class_name }}
                  <span v-if="s.room_name"> · {{ s.room_name }}</span>
                </div>
                <div v-if="s.note" class="ios-row-sub">{{ s.note }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section v-if="semester && board" class="ios-section" data-testid="dash-today">
      <div class="ios-section-title">今日调代课 · {{ boardDateLabel }}</div>
      <div class="ios-card">
        <div class="ios-card-body">
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
        </div>
      </div>
    </section>

    <!-- 仪表板教师个人节(2026-10-30 再定):请假/代课/调课已搬到调课管理页,
      通知已改成右上角小框,故这里只剩行政值日(只给行政岗位/管理员显示)
      与提醒设置(最后);管理员看不到这些个人节,仪表板对管理员仍是概览。 -->
    <TeacherHomeSections
      v-if="weekMe && weekSemester" :semester-id="weekSemester.id" :teacher-id="weekMe.id"
    />
  </div>
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
