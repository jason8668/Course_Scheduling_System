<script setup lang="ts">
import {
  NButton, NButtonGroup, NCard, NEmpty, NRadioButton, NRadioGroup, NSelect, NSpace, NTag, NText,
  useMessage,
} from 'naive-ui'
import { classLabel } from '@/utils/labels'
import { computed, onMounted, ref } from 'vue'
import { crossTableNote, extraRows } from '@/components/timetable/crossTable'
import TimetableGrid from '@/components/timetable/TimetableGrid.vue'
import type { GridEntry, PeriodCell } from '@/components/timetable/types'
import { getMyTeacher, getPublishedTimetable, publishedSemesters } from '@/api/timetables'
import type { NamedBrief, PublicSemester, PublishedTimetable } from '@/api/timetables'
import {
  exportBatchZip, exportSchoolWorkbook, exportTimetable,
} from '@/api/exports'
import type { ExportFmt } from '@/api/exports'
import { useAuthStore } from '@/stores/auth'

const semesters = ref<PublicSemester[]>([])
const sid = ref<number | null>(null)
const data = ref<PublishedTimetable | null>(null)
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
  ;[data.value, me.value] = await Promise.all([getPublishedTimetable(id), getMyTeacher(id)])
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
  <n-space vertical size="large">
    <n-space align="center" :wrap="true">
      <h1 style="margin: 0">课表查询</h1>
      <n-select
        v-if="semesters.length > 1" :value="sid" :options="semesterOptions"
        style="width: 200px" @update:value="load"
      />
      <n-tag v-if="data" size="small" type="success">
        {{ data.semester_label }} · {{ data.name }}(已发布)
      </n-tag>
    </n-space>

    <n-card v-if="!loading && !data" size="small">
      <n-empty description="目前尚无已发布的课表" data-testid="tq-none" />
    </n-card>

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

      <n-card size="small" data-testid="tq-grid">
        <n-empty v-if="periods.length === 0" description="此学期尚无节次表" />
        <TimetableGrid
          v-else
          :periods="periods" :num-weekdays="numWeekdays" :entries="entries" readonly
        />
      </n-card>
      <n-text depth="3" style="font-size: 12px">课表为唯读查看;如有异动请洽教学组。</n-text>
    </template>
  </n-space>
</template>
