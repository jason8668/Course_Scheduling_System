<script setup lang="ts">
import {
  NAlert, NButton, NDatePicker, NDrawer, NDrawerContent, NEmpty, NForm, NFormItem,
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
import { addDays, expandCalendarEvents, mondayOf, toISODate } from '@/utils/calendar'
import { classLabel } from '@/utils/labels'

const message = useMessage()
const auth = useAuthStore()
const canManage = computed(() =>
  auth.hasRole('admin') || auth.hasRole('scheduler') || auth.hasRole('director'))

const WEEKDAY_HEADS = ['一', '二', '三', '四', '五', '六', '日']
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

const now = new Date()
const viewYear = ref(now.getFullYear())
const viewMonth = ref(now.getMonth() + 1) // 1-12
const todayIso = toISODate(now)

const semester = computed(() => semesters.value.find((s) => s.id === sid.value) ?? null)
const semesterOptions = computed(() =>
  semesters.value.map((s) => ({ label: s.label, value: s.id })))
const monthTitle = computed(() => `${viewYear.value}年${viewMonth.value}月`)

/** 月历网格:6 行 × 7 列,周一起头(首格为当月 1 日所在周的周一)。 */
const gridStart = computed(() => mondayOf(new Date(viewYear.value, viewMonth.value - 1, 1)))
const gridEnd = computed(() => addDays(gridStart.value, 41))
const expanded = computed(() =>
  expandCalendarEvents(eventsRaw.value, toISODate(gridStart.value), toISODate(gridEnd.value)))

interface CalCell {
  iso: string
  dayNum: number
  inMonth: boolean
  isToday: boolean
  events: CalendarEvent[]
}
const cells = computed<CalCell[]>(() =>
  Array.from({ length: 42 }, (_, i) => {
    const d = addDays(gridStart.value, i)
    const iso = toISODate(d)
    return {
      iso,
      dayNum: d.getDate(),
      inMonth: d.getMonth() === viewMonth.value - 1,
      isToday: iso === todayIso,
      events: expanded.value.get(iso) ?? [],
    }
  }))

async function loadEvents() {
  if (sid.value === null) return
  loading.value = true
  try {
    eventsRaw.value = await listCalendarEvents(
      sid.value, toISODate(gridStart.value), toISODate(gridEnd.value))
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

function shiftMonth(delta: number) {
  const d = new Date(viewYear.value, viewMonth.value - 1 + delta, 1)
  viewYear.value = d.getFullYear()
  viewMonth.value = d.getMonth() + 1
  void loadEvents()
}
function backToThisMonth() {
  const d = new Date()
  viewYear.value = d.getFullYear()
  viewMonth.value = d.getMonth() + 1
  void loadEvents()
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

// ── 当天详情 ──
const showDay = ref(false)
const selectedDate = ref<string>(todayIso)
const dayEvents = computed(() => expanded.value.get(selectedDate.value) ?? [])
const selectedDateLabel = computed(() => {
  const d = new Date(`${selectedDate.value}T00:00:00`)
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`
})

function openDay(cell: CalCell) {
  selectedDate.value = cell.iso
  showDay.value = true
}

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

// ── 新增 / 编辑表单 ──
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
  form.value = emptyForm(dateIso ?? selectedDate.value ?? todayIso)
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
    </n-space>

    <n-alert v-if="semester && !semester.start_date" type="warning" data-testid="cal-nostart">
      本学期尚未设定开始日期，周次计算依赖它；请至「学期与节次表」补上学期开始日期。
    </n-alert>

    <n-empty v-if="!loading && sid === null" description="尚无可用学期" />

    <template v-else>
      <n-space align="center" :wrap="true">
        <n-button size="small" data-testid="cal-prev" @click="shiftMonth(-1)">上月</n-button>
        <strong style="font-size: 16px">{{ monthTitle }}</strong>
        <n-button size="small" data-testid="cal-next" @click="shiftMonth(1)">下月</n-button>
        <n-button size="small" quaternary @click="backToThisMonth()">回到本月</n-button>
        <n-text depth="3" style="font-size: 12px">点任一天查看当天活动</n-text>
      </n-space>

      <div class="cal-wrap">
        <div class="cal-heads">
          <div v-for="h in WEEKDAY_HEADS" :key="h" class="cal-head">周{{ h }}</div>
        </div>
        <div class="cal-grid" data-testid="cal-grid">
          <div
            v-for="cell in cells" :key="cell.iso"
            class="cal-cell" :class="{ 'is-other': !cell.inMonth, 'is-today': cell.isToday }"
            :data-date="cell.iso" @click="openDay(cell)"
          >
            <div class="cal-daynum">{{ cell.dayNum }}</div>
            <div
              v-for="ev in cell.events.slice(0, 3)" :key="ev.id"
              class="cal-chip"
              :style="{ background: TYPE_COLORS[ev.event_type].bg, color: TYPE_COLORS[ev.event_type].fg }"
              :title="ev.title"
            >
              {{ ev.title }}
            </div>
            <div v-if="cell.events.length > 3" class="cal-more">+{{ cell.events.length - 3 }}</div>
          </div>
        </div>
      </div>

      <n-space :wrap="true" size="small">
        <span
          v-for="(c, k) in TYPE_COLORS" :key="k" class="cal-legend"
          :style="{ background: c.bg, color: c.fg }"
        >{{ CALENDAR_EVENT_TYPE_LABELS[k as CalendarEventType] }}</span>
      </n-space>
    </template>

    <n-drawer v-model:show="showDay" :width="420" placement="right">
      <n-drawer-content :title="selectedDateLabel" closable>
        <n-space vertical>
          <n-button v-if="canManage" type="primary" @click="openCreate(selectedDate)">
            新增活动
          </n-button>
          <n-empty v-if="!dayEvents.length" description="当天没有校历活动" />
          <div v-for="ev in dayEvents" :key="ev.id" class="day-event">
            <n-space align="center" :wrap="true" size="small">
              <strong>{{ ev.title }}</strong>
              <n-tag
                size="small"
                :color="{ color: TYPE_COLORS[ev.event_type].bg, textColor: TYPE_COLORS[ev.event_type].fg }"
              >
                {{ CALENDAR_EVENT_TYPE_LABELS[ev.event_type] }}
              </n-tag>
              <n-tag v-if="ev.weekly_recurring" size="small" type="info">每周重复</n-tag>
            </n-space>
            <div class="day-event-meta">
              范围：{{ scopeText(ev) }} · 时间：{{ timeText(ev) }}
              <span v-if="ev.start_date !== ev.end_date || ev.weekly_recurring">
                · {{ ev.start_date }} 至 {{ ev.end_date }}
              </span>
            </div>
            <div v-if="ev.note" class="day-event-meta">备注：{{ ev.note }}</div>
            <n-space v-if="canManage" size="small" style="margin-top: 8px">
              <n-button size="small" @click="openEdit(ev)">编辑</n-button>
              <n-popconfirm @positive-click="onDelete(ev)">
                <template #trigger>
                  <n-button size="small" type="error">删除</n-button>
                </template>
                确定删除「{{ ev.title }}」？
              </n-popconfirm>
            </n-space>
          </div>
        </n-space>
      </n-drawer-content>
    </n-drawer>

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
.cal-wrap { background: #fff; border-radius: 12px; padding: 12px; box-shadow: 0 1px 2px rgba(8, 47, 66, 0.05), 0 10px 28px -14px rgba(8, 47, 66, 0.16); }
.cal-heads { display: grid; grid-template-columns: repeat(7, 1fr); gap: 6px; margin-bottom: 6px; }
.cal-head { text-align: center; font-weight: 600; font-size: 13px; color: #0b4257; padding: 4px 0; }
.cal-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 6px; }
.cal-cell {
  min-height: 96px; border: 1px solid #dde7ea; border-radius: 10px;
  padding: 6px; cursor: pointer; background: #fff; overflow: hidden;
}
.cal-cell:hover { border-color: #0d5a6e; }
.cal-cell.is-other { opacity: 0.45; }
.cal-cell.is-today { border: 2px solid #0d5a6e; background: rgba(13, 90, 110, 0.05); }
.cal-daynum { font-weight: 700; font-size: 13px; margin-bottom: 4px; }
.cal-chip {
  font-size: 11px; line-height: 1.5; padding: 1px 6px; border-radius: 999px;
  margin-bottom: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.cal-more { font-size: 11px; color: #5b6b73; }
.cal-legend { font-size: 12px; padding: 2px 10px; border-radius: 999px; }
.day-event { border: 1px solid #dde7ea; border-radius: 10px; padding: 10px 12px; }
.day-event-meta { margin-top: 6px; font-size: 13px; color: #5b6b73; }
</style>
