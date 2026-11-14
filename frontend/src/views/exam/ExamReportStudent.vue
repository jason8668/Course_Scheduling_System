<script setup lang="ts">
import { NButton, NEmpty, NSelect, NSpace, NText, useMessage } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import { formatScore, getExam, getStudentReportCard, listParticipants } from '@/api/exam'
import type { ExamDetail, StudentReportCard } from '@/api/exam'

// 学生个人成绩单页(KW-53,教师/教务完整版):各科成绩、总分、含排名,
// 可打印发放或电子发送给家长。版面照抄准考证打印页:白底黑框表 +
// @media print + window.print。学生从参试名单里选;支持从班级成绩单页
// 带 student_id 跳转进来。未发布时后端 403 的 detail 原样展示。

const message = useMessage()
const route = useRoute()
const router = useRouter()
const examId = Number(route.params.id)

const exam = ref<ExamDetail | null>(null)
const studentId = ref<number | null>(
  route.query.student_id ? Number(route.query.student_id) : null,
)
const card = ref<StudentReportCard | null>(null)
const loading = ref(false)
const forbidden = ref('')
const studentOptions = ref<{ label: string; value: number }[]>([])

const studentName = computed(() =>
  studentOptions.value.find((o) => o.value === studentId.value)?.label ?? '',
)

function goBack() {
  void router.push({ name: 'exam-exam-detail', params: { id: examId } })
}
function doPrint() {
  window.print()
}

async function reloadCard() {
  if (!studentId.value) { card.value = null; return }
  loading.value = true
  forbidden.value = ''
  try {
    card.value = await getStudentReportCard(examId, studentId.value)
  } catch (e) {
    card.value = null
    const err = e as ApiError
    if (err.status === 403) forbidden.value = err.detail || '无权查看该学生成绩单'
    else message.error(err.detail || '个人成绩单加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  loading.value = true
  try {
    exam.value = await getExam(examId)
    const res = await listParticipants(examId)
    studentOptions.value = res.items.map((p) => ({
      label: `${p.student_name}(${p.student_no}) ${p.class_name ?? ''}`,
      value: p.student_id,
    }))
    if (studentId.value) await reloadCard()
  } catch (e) {
    message.error((e as ApiError).detail || '加载失败')
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="sheet">
    <div class="no-print toolbar">
      <n-button text type="primary" @click="goBack">← 考试详情</n-button>
      <n-space :wrap="true" align="center" style="flex: 1; justify-content: flex-end">
        <n-select
          v-model:value="studentId" :options="studentOptions" filterable clearable
          placeholder="选择学生" style="width: 240px"
          data-testid="report-student-select" @update:value="reloadCard"
        />
        <n-button type="primary" :disabled="!card" data-testid="report-student-print-btn" @click="doPrint">打印</n-button>
      </n-space>
    </div>
    <n-text depth="3" class="no-print" style="font-size: 12px; display: block; margin-bottom: 12px">
      个人成绩单为教师/教务完整版,含总分与排名;给家长的版本按成绩单设置决定是否显示排名。
    </n-text>

    <h1 v-if="exam" class="head">{{ exam.name }} · 个人成绩单</h1>
    <p v-if="loading" class="empty">载入中…</p>
    <n-text v-else-if="forbidden" type="error" data-testid="report-student-forbidden" style="display: block; text-align: center">{{ forbidden }}</n-text>
    <n-empty v-else-if="!card" description="请先选择学生" />
    <div v-else class="card">
      <div class="card-title">成 绩 单</div>
      <div class="card-grid">
        <div><span class="k">姓名</span>{{ card.student_name }}</div>
        <div><span class="k">学号</span>{{ card.student_no }}</div>
        <div><span class="k">班级</span>{{ card.class_name }}</div>
        <div><span class="k">总分</span>{{ formatScore(card.total) }}</div>
        <div><span class="k">班级排名</span>{{ card.class_rank ?? '—' }}</div>
        <div><span class="k">年级排名</span>{{ card.grade_rank ?? '—' }}</div>
      </div>
      <table class="grid">
        <thead><tr><th>科目</th><th>成绩</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="s in card.subjects" :key="s.subject_id">
            <td>{{ s.subject_name }}</td>
            <td>{{ formatScore(s.score) }}</td>
            <td>{{ s.status }}</td>
          </tr>
        </tbody>
      </table>
      <div class="card-foot">总分 {{ formatScore(card.total) }} 分{{ studentName ? ` · ${studentName}` : '' }}</div>
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
.card { border: 2px solid #000; padding: 16px 20px; page-break-inside: avoid; }
.card-title { text-align: center; font-size: 20px; font-weight: 700; letter-spacing: 8px; margin-bottom: 12px; }
.card-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 24px;
  font-size: 15px;
  margin-bottom: 10px;
}
.card-grid .k { display: inline-block; width: 64px; font-weight: 600; }
.grid { border-collapse: collapse; width: 100%; table-layout: fixed; font-size: 13px; }
.grid th, .grid td { border: 1px solid #000; padding: 5px 6px; text-align: center; }
.grid th { background: #eee; }
.card-foot { font-size: 12px; color: #444; margin-top: 10px; }
.empty { text-align: center; padding: 40px 0; font-size: 15px; }

@media print {
  @page { size: A4 portrait; margin: 12mm; }
  .no-print { display: none !important; }
  .sheet { max-width: none; padding: 0; }
  .card { break-inside: avoid; page-break-inside: avoid; }
}
</style>

<style>
/* 打印页套在 MainLayout 内:打印时隐藏侧边栏与顶栏,只留本页内容。 */
@media print {
  .n-layout-sider, .app-header { display: none !important; }
}
</style>
