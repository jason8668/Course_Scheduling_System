<script setup lang="ts">
import {
  NAlert, NButton, NCard, NDatePicker, NEmpty, NForm, NFormItem,
  NInput, NInputNumber, NModal, NPopconfirm, NSelect, NSpace, NSwitch, NTag, NText,
  useMessage,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import {
  CALENDAR_EVENT_TYPE_LABELS, CALENDAR_SCOPE_LABELS,
  createCalendarEvent, deleteCalendarEvent, listCalendarEvents, updateCalendarEvent,
} from '@/api/calendar'
import type { CalendarEvent, CalendarEventType, CalendarScopeType } from '@/api/calendar'
import { listSemesters } from '@/api/semesters'
import { getPublishedTimetable, publishedSemesters } from '@/api/timetables'
import type { PublicClass, PublicSemester } from '@/api/timetables'
import { useAuthStore } from '@/stores/auth'
import {
  eventDateText, eventWeekText, groupEventsByMonth, monthsInRange, monthWeeks,
  resolveSemesterEnd, weekdayLabel, weekLabel,
} from '@/utils/calendarList'
import { classLabel } from '@/utils/labels'
import { expandCalendarEvents, toISODate as toISO } from '@/utils/calendar'

const message = useMessage()
const auth = useAuthStore()
const canManage = computed(() =>
  auth.hasRole('admin') || auth.hasRole('director'))

const TYPE_COLORS: Record<CalendarEventType, { bg: string; fg: string }> = {
  holiday: { bg: '#fdecea', fg: '#c0392b' },
  activity: { bg: '#eef6f8', fg: '#0d5a6e' },
  exam: { bg: '#fdf3e7', fg: '#c05621' },
  other: { bg: '#eef3fb', fg: '#2b6cb0' },
}

const semesters = ref<PublicSemester[]>([])
const sid = ref<number | null>(null)
const classes = ref<PublicClass[]>([])
const eventsRaw = ref<CalendarEvent[]>([])
const loading = ref(false)

const todayIso = toISO(new Date())

const semester = computed(() => semesters.value.find((s) => s.id === sid.value) ?? null)
const semesterOptions = computed(() =>
  semesters.value.map((s) => ({ label: s.label, value: s.id })))

// 一页一览:本学期全部活动(后端不传范围即返回全部),按开始月份分组。
const monthGroups = computed(() => groupEventsByMonth(eventsRaw.value))
const typeCounts = computed(() => {
  const m = new Map<CalendarEventType, number>()
  for (const ev of eventsRaw.value) m.set(ev.event_type, (m.get(ev.event_type) ?? 0) + 1)
  return m
})
const semesterRange = computed(() => {
  const s = semester.value
  if (!s) return ''
  if (s.start_date && s.end_date) return `${s.start_date} 至 ${s.end_date}`
  return s.start_date ?? s.end_date ?? ''
})

// ── 学期日历（月框）：从开学第一天到最后一天，每个月一个框 ──
const WEEKDAY_HEADS = ['一', '二', '三', '四', '五', '六', '日']
const rangeStart = computed(() => semester.value?.start_date ?? null)
const rangeEnd = computed(() =>
  resolveSemesterEnd(semester.value?.start_date ?? null, semester.value?.end_date ?? null))
const semesterMonths = computed(() =>
  rangeStart.value && rangeEnd.value ? monthsInRange(rangeStart.value, rangeEnd.value) : [])
// 把活动展开到学期范围内的每一天（每周重复按星期展开，与 Dashboard 覆盖逻辑一致）。
const expandedByDate = computed(() =>
  rangeStart.value && rangeEnd.value
    ? expandCalendarEvents(eventsRaw.value, rangeStart.value, rangeEnd.value)
    : new Map<string, CalendarEvent[]>())
interface FrameCell {
  iso: string
  dayNum: number
  inMonth: boolean
  inRange: boolean
  isToday: boolean
  events: CalendarEvent[]
}
const monthFrames = computed(() => semesterMonths.value.map((m) => ({
  ...m,
  weeks: monthWeeks(m.year, m.month).map((week) => week.map((cell): FrameCell => ({
    ...cell,
    inRange: rangeStart.value! <= cell.iso && cell.iso <= rangeEnd.value!,
    // 今天标记：同一周在两处同时标（10-26 同时出现在 10 月框与 11 月框补齐格时，两处都标），不限本月。
    isToday: cell.iso === todayIso,
    // 活动只在本月框内显示：跨月补齐格里的同一天不再重复出现活动。
    events: cell.inMonth ? (expandedByDate.value.get(cell.iso) ?? []) : [],
  }))),
})))

function onCellClick(cell: FrameCell) {
  // 学期范围外的补齐格不可点；教师点击只看，不打开任何编辑入口。
  if (!cell.inRange || !canManage.value) return
  openCreate(cell.iso)
}
function onChipClick(ev: CalendarEvent, e: MouseEvent) {
  e.stopPropagation()
  if (!canManage.value) return
  openEdit(ev)
}

// 有活动日期整格按类型颜色高亮（多类型取首条，标题字保留）。
// 今天格的描边由 .is-today 的琥珀虚线 + 「今日」徽标承担，这里只上活动底色，不盖掉今天标记。
function cellStyle(cell: FrameCell) {
  const ev = cell.events[0]
  if (!ev) return {}
  const c = TYPE_COLORS[ev.event_type]
  if (cell.isToday) return { background: c.bg }
  return { background: c.bg, borderColor: c.fg, borderWidth: '2px' }
}

async function loadEvents() {
  if (sid.value === null) return
  loading.value = true
  try {
    // 不传 from/to:一次拉取本学期全部活动,不再按月翻页取数。
    eventsRaw.value = await listCalendarEvents(sid.value)
  } catch {
    eventsRaw.value = []
  } finally {
    loading.value = false
  }
}

async function loadClasses() {
  if (sid.value === null) return
  try {
    const data = await getPublishedTimetable(sid.value)
    classes.value = data?.classes ?? []
  } catch {
    classes.value = []
  }
}

async function onSemesterChange(id: number) {
  sid.value = id
  await Promise.all([loadEvents(), loadClasses()])
}

function openPrint() {
  if (sid.value === null) return
  window.open(`/calendar/print?semester_id=${sid.value}`, '_blank')
}

onMounted(async () => {
  try {
    semesters.value = await publishedSemesters()
  } catch {
    semesters.value = []
  }
  if (!semesters.value.length) {
    // 退而求其次:管理学期清单(教师可能 403,失败就维持空)
    try {
      const items = await listSemesters()
      semesters.value = items.map((s) => ({
        id: s.id, label: s.label, start_date: s.start_date, end_date: s.end_date,
      }))
    } catch {
      semesters.value = []
    }
  }
  if (semesters.value.length) {
    sid.value = semesters.value[0].id
    await Promise.all([loadEvents(), loadClasses()])
  }
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

// ── 新增 / 编辑表单(字段与校验与旧版一致) ──
const showForm = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)

const emptyForm = (dateIso: string) => ({
  title: '',
  event_type: 'activity' as CalendarEventType,
  scope_type: 'school' as CalendarScopeType,
  scope_grade: null as number | null,
  scope_class_id: null as number | null,
  all_day: true,
  period_start: 1 as number | null,
  period_end: 1 as number | null,
  start_date: dateIso as string | null,
  end_date: dateIso as string | null,
  weekly_recurring: false,
  note: '' as string,
})
const form = ref(emptyForm(todayIso))

const typeOptions = (Object.keys(CALENDAR_EVENT_TYPE_LABELS) as CalendarEventType[])
  .map((k) => ({ label: CALENDAR_EVENT_TYPE_LABELS[k], value: k }))
const scopeOptions = (Object.keys(CALENDAR_SCOPE_LABELS) as CalendarScopeType[])
  .map((k) => ({ label: CALENDAR_SCOPE_LABELS[k], value: k }))
const gradeOptions = computed(() => {
  const grades = [...new Set(classes.value.map((c) => c.grade))].sort((a, b) => a - b)
  return grades.map((g) => ({ label: `${g}年级`, value: g }))
})
const classOptions = computed(() =>
  classes.value.map((c) => ({ label: classLabel(c), value: c.id })))

function openCreate(dateIso?: string) {
  editingId.value = null
  form.value = emptyForm(dateIso ?? todayIso)
  showForm.value = true
}
function openEdit(ev: CalendarEvent) {
  editingId.value = ev.id
  form.value = {
    title: ev.title,
    event_type: ev.event_type,
    scope_type: ev.scope_type,
    scope_grade: ev.scope_type === 'grade' ? ev.scope_id : null,
    scope_class_id: ev.scope_type === 'class' ? ev.scope_id : null,
    all_day: ev.period_start === null && ev.period_end === null,
    period_start: ev.period_start ?? 1,
    period_end: ev.period_end ?? ev.period_start ?? 1,
    start_date: ev.start_date,
    end_date: ev.end_date,
    weekly_recurring: ev.weekly_recurring,
    note: ev.note ?? '',
  }
  showForm.value = true
}

async function onSave() {
  if (sid.value === null) return
  const f = form.value
  if (!f.title.trim()) {
    message.warning('请填活动名称')
    return
  }
  if (!f.start_date || !f.end_date) {
    message.warning('请填开始与结束日期')
    return
  }
  if (f.end_date < f.start_date) {
    message.warning('结束日期不能早于开始日期')
    return
  }
  if (!f.all_day && (f.period_start == null || f.period_end == null || f.period_end < f.period_start)) {
    message.warning('请填正确的节次范围')
    return
  }
  const scopeId = f.scope_type === 'grade' ? f.scope_grade
    : f.scope_type === 'class' ? f.scope_class_id : null
  if (f.scope_type !== 'school' && scopeId == null) {
    message.warning(f.scope_type === 'grade' ? '请选择年级' : '请选择班级')
    return
  }
  saving.value = true
  try {
    const payload = {
      semester_id: sid.value,
      title: f.title.trim(),
      event_type: f.event_type,
      scope_type: f.scope_type,
      scope_id: scopeId,
      start_date: f.start_date,
      end_date: f.end_date,
      period_start: f.all_day ? null : f.period_start,
      period_end: f.all_day ? null : f.period_end,
      weekly_recurring: f.weekly_recurring,
      note: f.note.trim() ? f.note.trim() : null,
    }
    if (editingId.value !== null) {
      await updateCalendarEvent(editingId.value, payload)
      message.success('活动已更新')
    } else {
      await createCalendarEvent(payload)
      message.success('活动已新增')
    }
    showForm.value = false
    await loadEvents()
  } catch (e) {
    message.error((e as ApiError).detail || (e as Error).message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function onDelete(ev: CalendarEvent) {
  try {
    await deleteCalendarEvent(ev.id)
    message.success('活动已删除')
    await loadEvents()
  } catch (e) {
    message.error((e as ApiError).detail || (e as Error).message || '删除失败')
  }
}
</script>

<template>
  <n-space vertical size="large">
    <n-space align="center" :wrap="true">
      <h1 style="margin: 0">学校校历</h1>
      <n-select
        v-if="semesters.length" :value="sid" :options="semesterOptions"
        style="width: 220px" data-testid="cal-semester" @update:value="onSemesterChange"
      />
      <n-button v-if="canManage && sid !== null" type="primary" data-testid="cal-add" @click="openCreate()">
        新增活动
      </n-button>
      <n-button v-if="sid !== null" data-testid="cal-print" @click="openPrint">
        打印校历
      </n-button>
    </n-space>

    <n-alert v-if="semester && !semester.start_date" type="warning" data-testid="cal-nostart">
      本学期尚未设定开始日期，无法生成整学期日历；请至「学期与节次表」补上学期开始/结束日期。
    </n-alert>

    <n-empty v-if="!loading && sid === null" description="尚无可用学期" />

    <template v-else-if="sid !== null">
      <n-card data-testid="cal-overview">
        <n-space :wrap="true" size="large" align="center">
          <n-text strong>{{ semester?.label }}</n-text>
          <n-text v-if="semesterRange" depth="3">{{ semesterRange }}</n-text>
          <n-text>共 {{ eventsRaw.length }} 条活动</n-text>
          <span
            v-for="k in (Object.keys(CALENDAR_EVENT_TYPE_LABELS) as CalendarEventType[])" :key="k"
            class="cal-legend"
            :style="{ background: TYPE_COLORS[k].bg, color: TYPE_COLORS[k].fg }"
          >{{ CALENDAR_EVENT_TYPE_LABELS[k] }} {{ typeCounts.get(k) ?? 0 }}</span>
        </n-space>
      </n-card>

      <div v-if="semesterMonths.length" data-testid="cal-month-frames">
        <h2 class="cal-frames-title">学期日历</h2>
        <n-text v-if="semester && !semester.end_date" depth="3">
          结束日期未设定，按开学起 20 周显示。
        </n-text>
        <div class="month-frames">
          <section
            v-for="frame in monthFrames" :key="`${frame.year}-${frame.month}`" class="month-frame"
          >
            <h3 class="month-frame-title">{{ frame.label }}</h3>
            <div class="frame-heads">
              <div class="frame-head frame-weekno-head">周次</div>
              <div v-for="h in WEEKDAY_HEADS" :key="h" class="frame-head">周{{ h }}</div>
            </div>
            <div v-for="(week, wi) in frame.weeks" :key="wi" class="frame-week">
              <div class="frame-weekno">{{ weekLabel(rangeStart, week[0]!.iso) }}</div>
              <div
                v-for="cell in week" :key="cell.iso"
                class="frame-cell"
                :class="{ 'is-out': !cell.inRange, 'is-today': cell.isToday }"
                :style="cellStyle(cell)"
                @click="onCellClick(cell)"
              >
                <div class="frame-daynum">
                  {{ cell.dayNum }}<span v-if="cell.isToday" class="frame-today-badge">今日</span>
                </div>
                <div
                  v-for="ev in cell.events.slice(0, 2)" :key="ev.id"
                  class="frame-chip"
                  :style="{ background: TYPE_COLORS[ev.event_type].bg, color: TYPE_COLORS[ev.event_type].fg }"
                  :title="ev.title"
                  @click.stop="onChipClick(ev, $event)"
                >
                  {{ ev.title }}
                </div>
                <div v-if="cell.events.length > 2" class="frame-more">+{{ cell.events.length - 2 }}</div>
              </div>
            </div>
          </section>
        </div>
      </div>

      <n-empty v-if="!loading && !eventsRaw.length" description="本学期暂无校历活动">
        <template #extra>
          <n-button v-if="canManage" type="primary" @click="openCreate()">新增活动</n-button>
        </template>
      </n-empty>

      <div v-else data-testid="cal-groups">
        <section v-for="group in monthGroups" :key="group.month" class="cal-month">
          <h2 class="cal-month-title">{{ group.month }}</h2>
          <table class="cal-table">
            <thead>
              <tr>
                <th class="col-date">日期</th>
                <th class="col-weekno">周次</th>
                <th class="col-week">星期</th>
                <th>名称</th>
                <th class="col-type">类型</th>
                <th>范围</th>
                <th>时间</th>
                <th class="col-note">备注</th>
                <th v-if="canManage" class="col-actions">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="ev in group.events" :key="ev.id">
                <td class="col-date">{{ eventDateText(ev) }}</td>
                <td class="col-weekno">{{ eventWeekText(rangeStart, ev) }}</td>
                <td class="col-week">{{ weekdayLabel(ev.start_date) }}</td>
                <td><strong>{{ ev.title }}</strong></td>
                <td class="col-type">
                  <n-tag
                    size="small"
                    :color="{ color: TYPE_COLORS[ev.event_type].bg, textColor: TYPE_COLORS[ev.event_type].fg }"
                  >
                    {{ CALENDAR_EVENT_TYPE_LABELS[ev.event_type] }}
                  </n-tag>
                  <n-tag v-if="ev.weekly_recurring" size="small" type="info" style="margin-left: 4px">
                    每周重复
                  </n-tag>
                </td>
                <td>{{ scopeText(ev) }}</td>
                <td>{{ timeText(ev) }}</td>
                <td class="col-note">{{ ev.note ?? '—' }}</td>
                <td v-if="canManage" class="col-actions">
                  <n-space size="small">
                    <n-button size="small" @click="openEdit(ev)">编辑</n-button>
                    <n-popconfirm @positive-click="onDelete(ev)">
                      <template #trigger>
                        <n-button size="small" type="error">删除</n-button>
                      </template>
                      确定删除「{{ ev.title }}」？
                    </n-popconfirm>
                  </n-space>
                </td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>
    </template>

    <n-modal
      v-model:show="showForm" preset="card" style="width: min(560px, 92vw)"
      :title="editingId !== null ? '编辑活动' : '新增活动'"
    >
      <n-form label-placement="left" :label-width="88">
        <n-form-item label="名称">
          <n-input v-model:value="form.title" placeholder="如：秋季运动会" data-testid="cal-form-title" />
        </n-form-item>
        <n-form-item label="类型">
          <n-select v-model:value="form.event_type" :options="typeOptions" />
        </n-form-item>
        <n-form-item label="范围">
          <n-select v-model:value="form.scope_type" :options="scopeOptions" />
        </n-form-item>
        <n-form-item v-if="form.scope_type === 'grade'" label="年级">
          <n-select
            v-if="gradeOptions.length" v-model:value="form.scope_grade"
            :options="gradeOptions" placeholder="选择年级"
          />
          <n-input-number v-else v-model:value="form.scope_grade" :min="1" :max="12" placeholder="年级数" />
        </n-form-item>
        <n-form-item v-if="form.scope_type === 'class'" label="班级">
          <n-select
            v-model:value="form.scope_class_id" :options="classOptions"
            placeholder="选择班级" filterable
          />
        </n-form-item>
        <n-form-item label="全天">
          <n-switch v-model:value="form.all_day" />
        </n-form-item>
        <n-form-item v-if="!form.all_day" label="节次">
          <n-space align="center">
            <n-input-number v-model:value="form.period_start" :min="1" :max="16" style="width: 110px" />
            <span>至</span>
            <n-input-number v-model:value="form.period_end" :min="1" :max="16" style="width: 110px" />
            <span>节</span>
          </n-space>
        </n-form-item>
        <n-form-item label="开始日期">
          <n-date-picker
            v-model:formatted-value="form.start_date" value-format="yyyy-MM-dd"
            type="date" style="width: 100%"
          />
        </n-form-item>
        <n-form-item label="结束日期">
          <n-date-picker
            v-model:formatted-value="form.end_date" value-format="yyyy-MM-dd"
            type="date" style="width: 100%"
          />
        </n-form-item>
        <n-form-item label="每周重复">
          <n-switch v-model:value="form.weekly_recurring" />
        </n-form-item>
        <n-form-item label="备注">
          <n-input v-model:value="form.note" type="textarea" :rows="2" placeholder="可留空" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showForm = false">取消</n-button>
          <n-button type="primary" :loading="saving" data-testid="cal-form-save" @click="onSave">
            保存
          </n-button>
        </n-space>
      </template>
    </n-modal>
  </n-space>
</template>

<style scoped>
.cal-legend { font-size: 12px; padding: 2px 10px; border-radius: 999px; }
.cal-frames-title {
  font-size: 17px; font-weight: 700; color: #1d1d1f; margin: 4px 0 12px;
  padding-left: 10px; border-left: 4px solid #007aff;
}
.month-frames { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; margin-bottom: 28px; }
@media (max-width: 900px) { .month-frames { grid-template-columns: 1fr; } }
.month-frame {
  background: rgba(255, 255, 255, 0.72); border-radius: 16px; padding: 12px;
  -webkit-backdrop-filter: saturate(180%) blur(20px); backdrop-filter: saturate(180%) blur(20px);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04), 0 12px 32px -12px rgba(0, 90, 200, 0.18);
}
.month-frame-title { font-size: 15px; font-weight: 700; color: #1d1d1f; margin: 0 0 8px; }
.frame-heads, .frame-week { display: grid; grid-template-columns: 44px repeat(7, 1fr); gap: 4px; }
.frame-head { text-align: center; font-size: 12px; font-weight: 600; color: #1d1d1f; padding: 2px 0; }
.frame-weekno-head { color: #5b6b73; font-weight: 500; }
.frame-weekno {
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; color: #5b6b73; background: #f2f6f7; border-radius: 8px;
}
.frame-week { margin-bottom: 4px; }
.frame-cell {
  min-height: 64px; border: 1px solid #e6edf0; border-radius: 8px;
  padding: 4px; cursor: pointer; overflow: hidden; background: #fff;
}
.frame-cell:hover:not(.is-today) { border-color: #007aff; }
.frame-cell.is-out { opacity: 0.45; cursor: default; }
.frame-cell.is-out:hover { border-color: #e6edf0; }
/* 今天标记：琥珀虚线 + 「今日」徽标，与活动的实线彩色整格区分开（活动色的实线边框只在非今天格上）。 */
.frame-cell.is-today { border: 2px dashed #d97706; background: rgba(217, 119, 6, 0.08); }
.frame-daynum { display: flex; align-items: center; gap: 4px; font-size: 12px; font-weight: 700; margin-bottom: 2px; }
.frame-today-badge {
  font-size: 10px; font-weight: 600; color: #fff; background: #d97706;
  border-radius: 999px; padding: 0 5px; line-height: 1.6;
}
.frame-chip {
  font-size: 11px; line-height: 1.5; padding: 1px 5px; border-radius: 999px;
  margin-bottom: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.frame-more { font-size: 11px; color: #5b6b73; }
.cal-month { margin-bottom: 28px; }
.cal-month-title {
  font-size: 17px; font-weight: 700; color: #1d1d1f; margin: 0 0 10px;
  padding-left: 10px; border-left: 4px solid #007aff;
}
.cal-table { width: 100%; border-collapse: collapse; background: rgba(255, 255, 255, 0.72); border-radius: 16px; overflow: hidden; -webkit-backdrop-filter: saturate(180%) blur(20px); backdrop-filter: saturate(180%) blur(20px); box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04), 0 12px 32px -12px rgba(0, 90, 200, 0.18); }
.cal-table th, .cal-table td { border-bottom: 1px solid #dde7ea; padding: 9px 10px; text-align: left; font-size: 14px; }
.cal-table th { background: #eaf3ff; color: #0a4da6; }
.cal-table tr:last-child td { border-bottom: none; }
.col-date { white-space: nowrap; }
.col-weekno { white-space: nowrap; color: #86868b; }
.col-week { white-space: nowrap; }
.col-type { white-space: nowrap; }
.col-note { max-width: 220px; }
.col-actions { white-space: nowrap; }
</style>
