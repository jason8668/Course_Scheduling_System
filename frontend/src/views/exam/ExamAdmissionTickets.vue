<script setup lang="ts">
import { NButton, NEmpty, NSelect, NSpace, NText, useMessage } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import {
  filterTicketsByClass, getExam, listAdmissionTickets, sortTicketSubjects,
} from '@/api/exam'
import type { AdmissionTicket, AdmissionTicketSubject, ExamDetail } from '@/api/exam'
import { classLabel } from '@/utils/labels'

// 准考证打印页(KW-19):一名学生一张证,含姓名、考号、考场、座位号、
// 各科考试日程表;支持按班级分发打印。不带照片(无照片数据源)。
// 版面照抄课表打印页:白底黑框表 + @media print + window.print。

const message = useMessage()
const route = useRoute()
const router = useRouter()
const examId = Number(route.params.id)

const exam = ref<ExamDetail | null>(null)
const tickets = ref<AdmissionTicket[]>([])
const loading = ref(false)
const filterClass = ref<string | null>(null)

const classOptions = computed(() => {
  const seen = new Map<string, number | null>()
  for (const t of tickets.value) {
    if (t.class_name && !seen.has(t.class_name)) seen.set(t.class_name, t.grade ?? null)
  }
  return [...seen.entries()].map(([name, grade]) => ({ label: classLabel({ grade, name }), value: name }))
})
const shownTickets = computed(() => {
  const list = filterTicketsByClass(tickets.value, filterClass.value)
  return [...list].sort((a, b) => {
    if ((a.grade ?? 99) !== (b.grade ?? 99)) return (a.grade ?? 99) - (b.grade ?? 99)
    if ((a.class_name ?? '') !== (b.class_name ?? '')) {
      return (a.class_name ?? '').localeCompare(b.class_name ?? '', 'zh-CN')
    }
    return (a.exam_no ?? a.student_no).localeCompare(b.exam_no ?? b.student_no, 'zh-CN')
  })
})

function fmtTime(t?: string | null): string {
  return t ? t.slice(0, 5) : ''
}

/** 证面考场与座位号取首科;各科考场不同时以日程表为准。 */
function mainSubject(t: AdmissionTicket): AdmissionTicketSubject | null {
  const sorted = sortTicketSubjects(t.subjects ?? [])
  return sorted[0] ?? null
}
function roomsDiffer(t: AdmissionTicket): boolean {
  const rooms = new Set((t.subjects ?? []).map((s) => s.room_name ?? ''))
  return rooms.size > 1
}

function goBack() {
  void router.push({ name: 'exam-exam-arrange', params: { id: examId } })
}
function doPrint() {
  window.print()
}

onMounted(async () => {
  loading.value = true
  try {
    exam.value = await getExam(examId)
    tickets.value = (await listAdmissionTickets(examId)).items
  } catch (e) {
    message.error((e as ApiError).detail || '准考证加载失败')
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="sheet">
    <div class="no-print toolbar">
      <n-button text type="primary" @click="goBack">← 考场编排</n-button>
      <n-space :wrap="true" align="center" style="flex: 1; justify-content: flex-end">
        <n-select
          v-model:value="filterClass" :options="classOptions" clearable
          placeholder="全部班级(按班级分发打印)" style="width: 200px"
          data-testid="tickets-class-filter"
        />
        <n-button type="primary" data-testid="tickets-print-btn" @click="doPrint">打印</n-button>
      </n-space>
    </div>
    <n-text depth="3" class="no-print" style="font-size: 12px; display: block; margin-bottom: 12px">
      准考证不带照片(无照片数据源)。按班级筛选后打印,即按班级分发。
    </n-text>

    <h1 v-if="exam" class="head">{{ exam.name }} · 准考证</h1>
    <p v-if="loading" class="empty">载入中…</p>
    <n-empty v-else-if="shownTickets.length === 0" description="暂无准考证,请先完成考场编排" />
    <div v-for="t in shownTickets" :key="t.student_id" class="ticket">
      <div class="ticket-title">准 考 证</div>
      <div class="ticket-grid">
        <div><span class="k">姓名</span>{{ t.student_name }}</div>
        <div><span class="k">考号</span>{{ t.exam_no ?? '—' }}</div>
        <div><span class="k">班级</span>{{ classLabel({ grade: t.grade, name: t.class_name }) }}</div>
        <div><span class="k">学号</span>{{ t.student_no }}</div>
        <div><span class="k">考场</span>{{ mainSubject(t)?.room_name ?? '—' }}</div>
        <div><span class="k">座位号</span>{{ mainSubject(t)?.seat_no ?? '—' }}</div>
      </div>
      <div v-if="roomsDiffer(t)" class="ticket-note">各科考场与座位号不同,以各科日程表为准。</div>
      <table class="grid">
        <thead><tr><th>科目</th><th>考试日期</th><th>时间</th><th>考场</th><th>座位号</th></tr></thead>
        <tbody>
          <tr v-for="s in sortTicketSubjects(t.subjects ?? [])" :key="s.subject_id">
            <td>{{ s.subject_name }}</td>
            <td>{{ s.exam_date ?? '—' }}</td>
            <td>{{ fmtTime(s.start_time) }}-{{ fmtTime(s.end_time) }}</td>
            <td>{{ s.room_name ?? '—' }}</td>
            <td>{{ s.seat_no ?? '—' }}</td>
          </tr>
        </tbody>
      </table>
      <div class="ticket-foot">请携带本准考证,按时到指定考场参加考试。</div>
    </div>
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
.toolbar { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; }
.head { text-align: center; font-size: 19px; font-weight: 600; letter-spacing: 2px; margin: 0 0 16px; }
.ticket {
  border: 2px solid #000;
  padding: 16px 20px;
  margin-bottom: 20px;
  page-break-inside: avoid;
}
.ticket-title { text-align: center; font-size: 20px; font-weight: 700; letter-spacing: 8px; margin-bottom: 12px; }
.ticket-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 24px;
  font-size: 15px;
  margin-bottom: 10px;
}
.ticket-grid .k { display: inline-block; width: 64px; font-weight: 600; }
.ticket-note { font-size: 12px; color: #444; margin-bottom: 6px; }
.grid { border-collapse: collapse; width: 100%; table-layout: fixed; font-size: 13px; }
.grid th, .grid td { border: 1px solid #000; padding: 5px 6px; text-align: center; }
.grid th { background: #eee; }
.ticket-foot { font-size: 12px; color: #444; margin-top: 10px; }
.empty { text-align: center; padding: 40px 0; font-size: 15px; }

@media print {
  @page { size: A4 portrait; margin: 12mm; }
  .no-print { display: none !important; }
  .sheet { max-width: none; padding: 0; }
  .ticket { break-inside: avoid; page-break-inside: avoid; }
}
</style>

<style>
/* 打印页套在 MainLayout 内:打印时隐藏侧边栏与顶栏,只留本页内容。 */
@media print {
  .n-layout-sider, .app-header { display: none !important; }
}
</style>
