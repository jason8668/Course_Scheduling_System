<script setup lang="ts">
import {
  NAlert, NButton, NButtonGroup, NDatePicker, NEmpty, NRadioButton, NRadioGroup, NSelect, NSpace, NTag, NText,
  useMessage,
} from 'naive-ui'
import { classLabel } from '@/utils/labels'
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { crossTableNote, extraRows } from '@/components/timetable/crossTable'
import TimetableGrid from '@/components/timetable/TimetableGrid.vue'
import type { GridEntry, PeriodCell } from '@/components/timetable/types'
import {
  getActualTimetable, getMyTeacher, getPublishedTimetable, publishedSemesters,
} from '@/api/timetables'
import type {
  ActualDay, NamedBrief, PublicSemester, PublishedTimetable,
} from '@/api/timetables'
import { dutyNameForDate, dutyNameForWeekday, getDutyRoster } from '@/api/duty'
import type { DutyRoster } from '@/api/duty'
import {
  exportBatchZip, exportSchoolWorkbook, exportTimetable,
} from '@/api/exports'
import type { ExportFmt } from '@/api/exports'
import { useAuthStore } from '@/stores/auth'

const semesters = ref<PublicSemester[]>([])
const sid = ref<number | null>(null)
const data = ref<PublishedTimetable | null>(null)
const dutyRoster = ref<DutyRoster | null>(null)
const me = ref<NamedBrief | null>(null)
const loading = ref(true)

const message = useMessage()
const auth = useAuthStore()
const canManage = computed(() =>
  auth.hasRole('admin') || auth.hasRole('director'))

const view = ref<'class' | 'teacher' | 'room'>('class')
const classId = ref<number | null>(null)
const teacherId = ref<number | null>(null)
const roomId = ref<number | null>(null)
const exporting = ref(false)

// 实际课表模式:周课表是模板,某天实际是叠加了特殊日、请假代课、老师调课、放假后的那天真课表。
const mode = ref<'week' | 'day'>('week')
const router = useRouter()
const actualDateTs = ref<number | null>(null)
const actualDay = ref<ActualDay | null>(null)
const actualLoading = ref(false)
function localDate(ts: number): string {
  const d = new Date(ts)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
async function loadActual() {
  if (sid.value === null || actualDateTs.value === null) {
    actualDay.value = null
    return
  }
  actualLoading.value = true
  try {
    const ds = localDate(actualDateTs.value)
    const days = await getActualTimetable(sid.value, ds, ds)
    actualDay.value = days[0] ?? null
  } catch {
    actualDay.value = null
  } finally {
    actualLoading.value = false
  }
}
watch([mode, actualDateTs, sid], () => {
  if (mode.value === 'day' && actualDateTs.value === null) {
    actualDateTs.value = new Date().getTime()
  }
  if (mode.value === 'day') void loadActual()
})
const ORIGIN_LABELS: Record<string, string> = {
  base: '正常', substitute: '代课', special: '特殊日', teacher_swap: '老师调课',
  self_study: '自习', cancelled: '已取消', holiday: '放假', pending: '待处理', merge: '并班',
}
const ORIGIN_TAG: Record<string, string> = {
  base: 'default', substitute: 'warning', special: 'info', teacher_swap: 'info',
  self_study: 'default', cancelled: 'error', holiday: 'error', pending: 'error', merge: 'warning',
}
const actualSlots = computed(() => {
  const slots = actualDay.value?.slots ?? []
  if (view.value === 'class') return classId.value ? slots.filter((s) => s.class_unit_id === classId.value) : []
  if (view.value === 'teacher') return teacherId.value ? slots.filter((s) => s.teacher_ids.includes(teacherId.value!)) : []
  // 场地视角:实际槽位只带场地名,按名匹配(同名场地极少,名重复时以课表模板为准)
  const roomName = data.value?.rooms.find((r) => r.id === roomId.value)?.name
  return roomName ? slots.filter((s) => s.room_name === roomName) : []
})
const actualDuty = computed(() => {
  if (!actualDay.value) return ''
  return dutyNameForDate(dutyRoster.value, actualDay.value.date, actualDay.value.weekday) ?? ''
})

const targetId = computed(() =>
  view.value === 'class' ? classId.value
    : view.value === 'teacher' ? teacherId.value : roomId.value)

async function onExport(fmt: ExportFmt) {
  if (sid.value === null || targetId.value === null) return
  exporting.value = true
  try {
    await exportTimetable(sid.value, view.value, targetId.value, fmt)
  } catch (e) {
    message.error((e as Error).message || '导出失败')
  } finally {
    exporting.value = false
  }
}

/** 打印目前视角的课表(新分頁开打印页,供打印出来张贴)。 */
function openPrint() {
  if (sid.value === null || targetId.value === null) return
  const url = `/timetable/print?semester_id=${sid.value}&view=${view.value}&id=${targetId.value}`
  window.open(url, '_blank')
}

// 全校导出跟著目前的查看走:班级视角出班级版,教师视角出教师版(用户回报 #22)。
// 场地没有这个需求,切到场地时不显示这两个按钮。
const batchView = computed<'class' | 'teacher' | null>(() =>
  view.value === 'class' || view.value === 'teacher' ? view.value : null)
const batchLabel = computed(() => (batchView.value === 'teacher' ? '全校教师' : '全校班级'))

async function onExportAll(kind: 'school' | 'batch') {
  if (sid.value === null || batchView.value === null) return
  exporting.value = true
  try {
    await (kind === 'school'
      ? exportSchoolWorkbook(sid.value, batchView.value)
      : exportBatchZip(sid.value, batchView.value))
  } catch (e) {
    message.error((e as Error).message || '导出失败')
  } finally {
    exporting.value = false
  }
}

const semesterOptions = computed(() => semesters.value.map((s) => ({ label: s.label, value: s.id })))
const classOptions = computed(() =>
  (data.value?.classes ?? []).map((c) => ({ label: classLabel(c), value: c.id })))
const teacherOptions = computed(() =>
  (data.value?.teachers ?? []).map((t) => ({ label: t.name, value: t.id })))
const roomOptions = computed(() =>
  (data.value?.rooms ?? []).map((r) => ({ label: r.name, value: r.id })))

async function load(id: number) {
  sid.value = id
  ;[data.value, me.value, dutyRoster.value] = await Promise.all([
    getPublishedTimetable(id), getMyTeacher(id), getDutyRoster(id).catch(() => null),
  ])
  const d = data.value
  if (!d) return
  classId.value = d.classes[0]?.id ?? null
  roomId.value = d.rooms[0]?.id ?? null
  // 教师登录且已绑定 → 默认显示本人课表
  if (me.value) {
    view.value = 'teacher'
    teacherId.value = me.value.id
  } else {
    teacherId.value = d.teachers[0]?.id ?? null
  }
}

onMounted(async () => {
  try {
    semesters.value = await publishedSemesters()
    if (semesters.value.length) await load(semesters.value[0].id)
  } finally {
    loading.value = false
  }
})

const defaultTable = computed(() => {
  const ts = data.value?.period_tables ?? []
  return ts.find((t) => t.is_default) ?? ts[0] ?? null
})
/** 班级视角用该班所属节次表;教师/场地视角用学期默认表。 */
const activeTable = computed(() => {
  if (view.value === 'class' && classId.value) {
    const c = data.value?.classes.find((x) => x.id === classId.value)
    if (c?.period_table_id) {
      return data.value?.period_tables.find((t) => t.id === c.period_table_id) ?? defaultTable.value
    }
  }
  return defaultTable.value
})
const numWeekdays = computed(() => activeTable.value?.num_weekdays ?? 5)

const shownEntries = computed(() => {
  const all = data.value?.entries ?? []
  if (view.value === 'class') return classId.value ? all.filter((e) => e.class_ids.includes(classId.value!)) : []
  if (view.value === 'teacher') return teacherId.value ? all.filter((e) => e.teacher_ids.includes(teacherId.value!)) : []
  return roomId.value ? all.filter((e) => e.room_id === roomId.value) : []
})
/** 教师/场地视角:默认表没有、但这位老师(这间场地)用得到的节次列要补上(如高中部的第八节)。 */
const periods = computed<PeriodCell[]>(() => {
  const base = (activeTable.value?.periods ?? []) as PeriodCell[]
  if (view.value === 'class') return base
  return [...base, ...extraRows(
    shownEntries.value, data.value?.classes ?? [], data.value?.period_tables ?? [], activeTable.value,
  ) as PeriodCell[]]
})

const dutyText = computed(() => {
  const parts: string[] = []
  for (let w = 1; w <= numWeekdays.value; w++) {
    const name = dutyNameForWeekday(dutyRoster.value, w)
    if (name) parts.push(`周${['一', '二', '三', '四', '五', '六', '日'][w - 1]} ${name}`)
  }
  return parts.join(' · ')
})

const entries = computed<GridEntry[]>(() => {
  return shownEntries.value.map((e) => ({
    id: e.id, weekday: e.weekday, period_no: e.period_no, span: e.span, locked: false,
    subject: e.subject,
    teacher: view.value === 'class' ? e.teachers.join('、') : e.classes.join('、'),
    room: e.room ?? undefined,
    // 教师/场地视角照默认节次表画格线;另一套节次表的课要标出实际时间
    note: view.value === 'class' ? undefined : crossTableNote(
      e, data.value?.classes ?? [], data.value?.period_tables ?? [], activeTable.value),
    // 单双周(v1.3.0):同一格单周、双周两堂上下并列
    week: e.week_parity === 'odd' ? '单' as const : e.week_parity === 'even' ? '双' as const : undefined,
  }))
})
</script>

<template>
  <div class="ios-page">
    <n-space align="center" :wrap="true">
      <h1 class="ios-title">课表查询</h1>
      <n-select
        v-if="semesters.length > 1" :value="sid" :options="semesterOptions"
        style="width: 200px" @update:value="load"
      />
      <n-tag v-if="data" size="small" type="success">
        {{ data.semester_label }} · {{ data.name }}(已发布)
      </n-tag>
    </n-space>

    <section v-if="!loading && !data" class="ios-section">
      <div class="ios-card">
        <div class="ios-card-body">
      <n-empty description="目前尚无已发布的课表" data-testid="tq-none" />
        </div>
      </div>
    </section>

    <template v-else-if="data">
      <n-space align="center" :wrap="true">
        <n-radio-group v-model:value="view">
          <n-radio-button value="class" data-testid="tq-view-class">班级</n-radio-button>
          <n-radio-button value="teacher" data-testid="tq-view-teacher">教师</n-radio-button>
          <n-radio-button value="room" data-testid="tq-view-room">场地</n-radio-button>
        </n-radio-group>
        <n-select
          v-if="view === 'class'" v-model:value="classId" data-testid="tq-class"
          :options="classOptions" style="width: 160px" filterable
        />
        <n-select
          v-else-if="view === 'teacher'" v-model:value="teacherId" data-testid="tq-teacher"
          :options="teacherOptions" style="width: 160px" filterable
        />
        <n-select
          v-else v-model:value="roomId" data-testid="tq-room"
          :options="roomOptions" style="width: 160px" filterable
        />
        <n-tag v-if="me && view === 'teacher' && teacherId === me.id" size="small" type="info">
          本人课表
        </n-tag>
      </n-space>

      <n-space align="center" :wrap="true">
        <n-radio-group v-model:value="mode">
          <n-radio-button value="week" data-testid="tq-mode-week">周课表(模板)</n-radio-button>
          <n-radio-button value="day" data-testid="tq-mode-day">某天实际课表</n-radio-button>
        </n-radio-group>
        <n-date-picker
          v-if="mode === 'day'" v-model:value="actualDateTs" type="date"
          placeholder="选日期" style="width: 160px" data-testid="tq-actual-date"
        />
        <n-text v-if="mode === 'day'" depth="3" style="font-size: 12px">
          实际课表已叠加特殊日、请假代课、老师调课和放假,看到的就是那天真要上的课。
        </n-text>
      </n-space>

      <n-space align="center" :wrap="true">
        <n-text depth="3" style="font-size: 13px">导出目前课表:</n-text>
        <n-button-group>
          <n-button
            size="small" :disabled="targetId === null || exporting"
            data-testid="export-xlsx" @click="onExport('xlsx')"
          >
            Excel
          </n-button>
          <n-button
            size="small" :loading="exporting" :disabled="targetId === null"
            data-testid="export-pdf" @click="onExport('pdf')"
          >
            PDF
          </n-button>
          <n-button
            size="small" :loading="exporting" :disabled="targetId === null"
            data-testid="export-png" @click="onExport('png')"
          >
            PNG
          </n-button>
        </n-button-group>
        <n-button
          size="small" type="primary" ghost :disabled="targetId === null"
          data-testid="tq-print" @click="openPrint"
        >
          打印课表
        </n-button>
        <template v-if="canManage && batchView">
          <n-text depth="3" style="font-size: 13px">{{ batchLabel }}:</n-text>
          <n-button
            size="small" :disabled="exporting" data-testid="export-school"
            @click="onExportAll('school')"
          >
            总表 Excel
          </n-button>
          <n-button
            size="small" :disabled="exporting" data-testid="export-batch"
            @click="onExportAll('batch')"
          >
            批次 zip
          </n-button>
          <n-text depth="3" style="font-size: 12px">
            {{ batchView === 'teacher' ? '每位在职教师一张(含没排到课的)' : '每班一张' }}
          </n-text>
        </template>
      </n-space>

      <section v-if="mode === 'day'" class="ios-section" data-testid="tq-actual">
        <div class="ios-card">
          <div class="ios-card-body">
            <n-text v-if="actualLoading">加载中…</n-text>
            <n-empty v-else-if="!actualDay || !actualDay.published" description="该学期尚未发布课表,暂无实际课表" />
            <template v-else>
              <n-alert
                v-if="actualDay.holiday_titles.length" type="error" style="margin-bottom: 8px"
              >
                {{ actualDay.date }} 放假({{ actualDay.holiday_titles.join('、') }}),以下为取消的课。
              </n-alert>
              <n-alert
                v-if="actualDay.workday_pending" type="warning" style="margin-bottom: 8px"
              >
                {{ actualDay.date }} 是调休上班日({{ actualDay.workday_title }}),还没复制课表。
                <n-button size="small" type="primary" @click="router.push({ name: 'scheduling-center' })">
                  去排课中心复制
                </n-button>
              </n-alert>
              <n-alert
                v-else-if="actualDay.workday_title" type="info" style="margin-bottom: 8px"
              >
                {{ actualDay.date }} 是调休上班日({{ actualDay.workday_title }}),以下为复制的课表。
              </n-alert>
              <n-empty v-if="!actualSlots.length" description="这天没有课" />
              <div v-for="s in actualSlots" :key="`${s.class_unit_id}-${s.period_no}`" class="ios-row" data-testid="tq-actual-row">
                <div class="ios-row-main">
                  <div class="ios-row-title">
                    第{{ s.period_no }}节 {{ s.subject }}
                    <span v-if="view === 'class'"> · {{ s.teacher_names.join('、') || '—' }}</span>
                    <span v-else> · {{ s.class_name }}</span>
                    <span v-if="s.room_name"> · {{ s.room_name }}</span>
                  </div>
                  <div v-if="s.note" class="ios-row-sub">{{ s.note }}</div>
                </div>
                <n-tag :type="(ORIGIN_TAG[s.origin] ?? 'default') as never" size="small">
                  {{ ORIGIN_LABELS[s.origin] ?? s.origin }}
                </n-tag>
              </div>
              <n-text depth="3" style="font-size: 13px" data-testid="tq-actual-duty">
                行政值日: {{ actualDuty || '尚未安排（请管理员在系统管理页排每周轮值）' }}
              </n-text>
            </template>
          </div>
        </div>
      </section>
      <section v-else class="ios-section" data-testid="tq-grid">
        <div class="ios-card">
          <div class="ios-card-body">
        <n-empty v-if="periods.length === 0" description="此学期尚无节次表" />
        <TimetableGrid
          v-else
          :periods="periods" :num-weekdays="numWeekdays" :entries="entries" readonly
        />
        <!-- 值日行一直画:没排轮值时 dutyText 为空,之前 v-if 把整行藏掉,
          看起来就像「值日信息没有写进去」;现在没排就明写尚未安排。 -->
        <n-text depth="3" style="font-size: 13px" data-testid="tq-duty">
          行政值日: {{ dutyText || '尚未安排（请管理员在系统管理页排每周轮值）' }}
        </n-text>
          </div>
        </div>
      </section>
      <n-text depth="3" style="font-size: 12px">课表为唯读查看;如有异动请洽教学组。</n-text>
    </template>
  </div>
</template>
