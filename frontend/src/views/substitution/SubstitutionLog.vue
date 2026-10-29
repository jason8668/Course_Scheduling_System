<script setup lang="ts">
import { NAlert, NButton, NDatePicker, NEmpty, NSelect, NSpace, NTag, NText } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { listTeachers } from '@/api/basedata'
import { listLeaveTypes } from '@/api/leaves'
import { listSemesters } from '@/api/semesters'
import { getSubstitutionLog } from '@/api/substitutionLog'
import type { LogEntry } from '@/api/substitutionLog'
import { openSlips } from '@/api/substitutions'

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

function toISODate(ts: number): string {
  const d = new Date(ts)
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}
function withWeekday(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return `${iso}(${WEEKDAYS[new Date(y, m - 1, d).getDay()]})`
}

const semesters = ref<{ id: number; label: string }[]>([])
const sid = ref<number | null>(null)
const teacherOptions = ref<{ label: string; value: number }[]>([])
const leaveTypes = ref<Record<string, string>>({})

const teacherId = ref<number | null>(null)
const range = ref<[number, number] | null>(null)
const leaveType = ref<string | null>(null)
const entries = ref<LogEntry[]>([])
const loading = ref(false)

// 后端的保护性上限(substitution_log.MAX_ROWS)。取到刚好这么多笔,几乎必然是被截断了——
// 不讲的话,组长会以为「这学期就只有这些纪录」,而看不见的那些正是他要找的旧资料。
const MAX_ROWS = 1000
const truncated = computed(() => entries.value.length >= MAX_ROWS)

const semesterOptions = computed(() => semesters.value.map((s) => ({ label: s.label, value: s.id })))
const leaveTypeOptions = computed(() =>
  Object.entries(leaveTypes.value).map(([value, label]) => ({ label, value })))

async function reload() {
  if (sid.value === null) return
  loading.value = true
  try {
    entries.value = await getSubstitutionLog(sid.value, {
      teacherId: teacherId.value,
      dateFrom: range.value ? toISODate(range.value[0]) : null,
      dateTo: range.value ? toISODate(range.value[1]) : null,
      leaveType: leaveType.value,
    })
  } finally {
    loading.value = false
  }
}

async function onSemesterChange(id: number) {
  sid.value = id
  teacherOptions.value = (await listTeachers(id)).map((t) => ({ label: t.name, value: t.id }))
  await reload()
}

function resetFilters() {
  teacherId.value = null
  range.value = null
  leaveType.value = null
  reload()
}

onMounted(async () => {
  ;[semesters.value, leaveTypes.value] = await Promise.all([listSemesters(), listLeaveTypes()])
  if (semesters.value.length) await onSemesterChange(semesters.value[0].id)
})

// 筛选结果中还有效的调课/代课:依日期区间筛出本周(或某位老师)的处置,一次印齐
const swapIds = computed(() => entries.value
  .filter((e) => e.sub_type === 'swap' && e.status !== 'cancelled')
  .map((e) => e.affected_period_id))

const substituteIds = computed(() => entries.value
  .filter((e) => (e.sub_type === 'substitute' || e.sub_type === 'merge')
    && e.status !== 'cancelled')
  .map((e) => e.affected_period_id))

function printSlips(kind: 'swap' | 'substitute') {
  if (sid.value) openSlips(kind, sid.value, kind === 'swap' ? swapIds.value : substituteIds.value)
}

function dispositionText(e: LogEntry): string {
  if (!e.disposed) return '—'
  if (e.handler_name) return `${e.sub_type_label} · ${e.handler_name}`
  return e.sub_type_label ?? ''
}

function statusType(e: LogEntry): string {
  if (e.status === 'pending') return 'warning'
  if (e.status === 'cancelled') return 'default'
  if (e.status === 'completed') return 'info'
  return 'success'
}
</script>

<template>
  <div class="ios-page">
    <h1 class="ios-title">调代课纪录</h1>

    <n-space align="center" :wrap="true">
      <n-select
        :value="sid" :options="semesterOptions" style="width: 200px"
        placeholder="选择学期" @update:value="onSemesterChange"
      />
      <n-select
        v-model:value="teacherId" :options="teacherOptions" clearable filterable
        placeholder="教师(缺课或代课)" style="width: 200px"
        data-testid="log-teacher" @update:value="reload"
      />
      <n-date-picker
        v-model:value="range" type="daterange" clearable style="width: 260px"
        data-testid="log-range" @update:value="reload"
      />
      <n-select
        v-model:value="leaveType" :options="leaveTypeOptions" clearable
        placeholder="假别" style="width: 130px"
        data-testid="log-leavetype" @update:value="reload"
      />
      <n-button quaternary data-testid="log-reset" @click="resetFilters">清除</n-button>
    </n-space>

    <n-space align="center">
      <n-text depth="3" data-testid="log-count">共 {{ entries.length }} 笔</n-text>
      <n-button
        v-if="swapIds.length" size="small" data-testid="log-print-slips"
        @click="printSlips('swap')"
      >
        打印这些纪录中的调课单({{ swapIds.length }} 节)
      </n-button>
      <n-button
        v-if="substituteIds.length" size="small" data-testid="log-print-sub-slips"
        @click="printSlips('substitute')"
      >
        打印这些纪录中的代课单({{ substituteIds.length }} 节)
      </n-button>
    </n-space>

    <n-alert v-if="truncated" type="warning" :bordered="false" data-testid="log-truncated">
      只显示最新的 {{ MAX_ROWS }} 笔,更早的纪录未列出。请缩小日期区间,或加上教师、假别筛选。
    </n-alert>

    <n-empty
      v-if="!entries.length && !loading" description="没有符合条件的纪录"
      data-testid="log-empty"
    />
    <table v-else-if="entries.length" class="ios-table" data-testid="log-table">
      <thead>
        <tr>
          <th>日期</th><th>节次</th><th>班级</th><th>科目</th>
          <th>原任教师</th><th>假别</th><th>处置</th><th>状态</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="e in entries" :key="e.affected_period_id" data-testid="log-row">
          <td>{{ withWeekday(e.date) }}</td>
          <td>{{ e.period_name }}</td>
          <td>{{ e.class_names }}</td>
          <td>{{ e.subject_name }}</td>
          <td>{{ e.absent_teacher_name }}</td>
          <td>{{ e.leave_type_label }}</td>
          <td>{{ dispositionText(e) }}</td>
          <td><n-tag size="small" :type="statusType(e) as never">{{ e.status_label }}</n-tag></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
