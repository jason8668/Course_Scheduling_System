<script setup lang="ts">
import {
  NButton, NButtonGroup, NDatePicker, NEmpty, NSelect, NSpace, NTag, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { exportPatrolSheets, getDailyBoard, openPatrolSheets } from '@/api/substitutionLog'
import type { DailyBoard, LogEntry } from '@/api/substitutionLog'
import { listSemesters } from '@/api/semesters'

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

// NDatePicker 给的是毫秒时间戳;以本机日期组出 YYYY-MM-DD,避免 toISOString 的 UTC 倒退
function toISODate(ts: number): string {
  const d = new Date(ts)
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}
function todayTs(): number {
  const d = new Date()
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

function parseISODate(iso: string): number {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d).getTime()
}

const route = useRoute()
const message = useMessage()
const semesters = ref<{ id: number; label: string }[]>([])
const sid = ref<number | null>(null)
const dateTs = ref<number>(
  typeof route.query.date === 'string' ? parseISODate(route.query.date) : todayTs())
const board = ref<DailyBoard | null>(null)
const loading = ref(false)

const semesterOptions = computed(() => semesters.value.map((s) => ({ label: s.label, value: s.id })))
const dateLabel = computed(() =>
  board.value ? `${board.value.date}(${WEEKDAYS[board.value.weekday % 7]})` : '')

async function reload() {
  if (sid.value === null) return
  loading.value = true
  try {
    board.value = await getDailyBoard(sid.value, toISODate(dateTs.value))
  } finally {
    loading.value = false
  }
}

async function onSemesterChange(id: number) {
  sid.value = id
  await reload()
}

onMounted(async () => {
  semesters.value = await listSemesters()
  if (!semesters.value.length) return
  const qsid = Number(route.query.semester_id)
  const initial = semesters.value.find((s) => s.id === qsid)?.id ?? semesters.value[0].id
  await onSemesterChange(initial)
})

function openPrint() {
  if (sid.value === null) return
  const url = `/daily-board/print?semester_id=${sid.value}&date=${toISODate(dateTs.value)}`
  window.open(url, '_blank')
}

/** 课堂巡视情况记录表的范围:当天,或选定日期那一周(周一到周日;没课的日子后端会略过) */
function patrolRange(week: boolean): [string, string] {
  if (!week) return [toISODate(dateTs.value), toISODate(dateTs.value)]
  const d = new Date(dateTs.value)
  const monday = new Date(d.getFullYear(), d.getMonth(), d.getDate() - ((d.getDay() + 6) % 7))
  const sunday = new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + 6)
  return [toISODate(monday.getTime()), toISODate(sunday.getTime())]
}

function openPatrol(week: boolean) {
  if (sid.value === null) return
  openPatrolSheets(sid.value, ...patrolRange(week))
}

// 导出 Excel:打印页印出来就不能改,学校常要再加栏位、填巡视人员
const exportingPatrol = ref(false)
async function exportPatrol(week: boolean) {
  if (sid.value === null) return
  exportingPatrol.value = true
  try {
    await exportPatrolSheets(sid.value, ...patrolRange(week))
  } catch (e) {
    message.error((e as Error).message || '导出失败')
  } finally {
    exportingPatrol.value = false
  }
}

function dispositionText(e: LogEntry): string {
  if (!e.disposed) return '待安排'
  if (e.row_kind === 'swap_makeup') {
    return `调课补课 · ${e.handler_name}(与 ${e.swap_date} ${e.swap_period_name} 对调)`
  }
  if (e.sub_type === 'swap' && e.swap_period_name) {
    return `调课 · ${e.handler_name}(补 ${e.swap_date} ${e.swap_period_name})`
  }
  if (e.handler_name) return `${e.sub_type_label} · ${e.handler_name}`
  return e.sub_type_label ?? ''
}

function statusType(e: LogEntry): string {
  if (e.status === 'pending') return 'warning'
  if (e.status === 'completed') return 'info'
  return 'success'
}
</script>

<template>
  <n-space vertical size="large">
    <n-space align="center" :wrap="true">
      <h2 style="margin: 0">今日调代课看板</h2>
      <n-select
        :value="sid" :options="semesterOptions" style="width: 200px"
        placeholder="选择学期" @update:value="onSemesterChange"
      />
      <n-date-picker
        v-model:value="dateTs" type="date" style="width: 160px"
        data-testid="board-date" @update:value="reload"
      />
      <n-button
        v-if="board?.entries.length" type="primary" data-testid="board-print"
        @click="openPrint"
      >
        打印通知单
      </n-button>
      <template v-if="sid !== null">
        <n-text depth="3">课堂巡视情况记录表:</n-text>
        <n-button-group>
          <n-button data-testid="board-patrol" @click="openPatrol(false)">打印当天</n-button>
          <n-button data-testid="board-patrol-week" @click="openPatrol(true)">打印整周</n-button>
        </n-button-group>
        <n-button-group>
          <n-button
            :loading="exportingPatrol" data-testid="board-patrol-xlsx" @click="exportPatrol(false)"
          >
            当天 Excel
          </n-button>
          <n-button
            :loading="exportingPatrol" data-testid="board-patrol-week-xlsx" @click="exportPatrol(true)"
          >
            整周 Excel
          </n-button>
        </n-button-group>
      </template>
    </n-space>

    <n-text v-if="board" depth="3" data-testid="board-datelabel">{{ dateLabel }}</n-text>

    <n-empty
      v-if="board && !board.entries.length && !loading"
      description="今日无调代课" data-testid="board-empty" style="padding: 40px 0"
    />

    <table v-else-if="board?.entries.length" class="data-table" data-testid="board-table">
      <thead>
        <tr>
          <th>节次</th><th>班级</th><th>科目</th><th>原任教师</th>
          <th>假别</th><th>处置</th><th>状态</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="e in board.entries" :key="`${e.row_kind}-${e.affected_period_id}`"
          data-testid="board-row"
        >
          <td>{{ e.period_name }}</td>
          <td>{{ e.class_names }}<n-text v-if="e.room_name" depth="3"> @{{ e.room_name }}</n-text></td>
          <td>{{ e.subject_name }}</td>
          <td>{{ e.absent_teacher_name }}</td>
          <td>{{ e.leave_type_label }}</td>
          <td :class="{ pending: !e.disposed }">{{ dispositionText(e) }}</td>
          <td>
            <n-tag size="small" :type="statusType(e) as never">{{ e.status_label }}</n-tag>
          </td>
        </tr>
      </tbody>
    </table>
  </n-space>
</template>

<style scoped>
.data-table { border-collapse: collapse; width: 100%; }
.data-table th, .data-table td {
  border: 1px solid var(--n-border-color, #e0e0e0); padding: 6px 10px; text-align: left;
}
.data-table th { background: rgba(128, 128, 128, 0.08); font-weight: 600; }
.pending { color: #e08000; }
</style>
