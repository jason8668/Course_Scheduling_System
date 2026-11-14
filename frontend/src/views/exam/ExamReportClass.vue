<script setup lang="ts">
import { NButton, NEmpty, NSelect, NSpace, NText, useMessage } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import { formatScore, getClassReportCard, getExam } from '@/api/exam'
import type { ClassReportCard, ExamDetail } from '@/api/exam'
import { listClassUnits } from '@/api/basedata'
import type { ClassUnit } from '@/api/basedata'

// 班级成绩单打印页(KW-52):按班级出全科成绩单(班主任版,含总分与排名),
// 供班主任核对和存档。版面照抄准考证打印页:白底黑框表 + @media print + window.print。
// 排名以后端为准,前端不重算;未发布时后端 403 的 detail 原样展示。

const message = useMessage()
const route = useRoute()
const router = useRouter()
const examId = Number(route.params.id)

const exam = ref<ExamDetail | null>(null)
const classes = ref<ClassUnit[]>([])
const classId = ref<number | null>(null)
const card = ref<ClassReportCard | null>(null)
const loading = ref(false)
const forbidden = ref('')

const classOptions = computed(() =>
  classes.value.map((c) => ({ label: `${c.grade} 年级 ${c.name}`, value: c.id })),
)
const subjects = computed(() => card.value?.students[0]?.subjects ?? [])

function goBack() {
  void router.push({ name: 'exam-exam-detail', params: { id: examId } })
}
function goStudentCard(studentId: number) {
  void router.push({
    name: 'exam-exam-report-student',
    params: { id: examId },
    query: { student_id: String(studentId) },
  })
}
function doPrint() {
  window.print()
}

async function reloadCard() {
  if (!classId.value) { card.value = null; return }
  loading.value = true
  forbidden.value = ''
  try {
    card.value = await getClassReportCard(examId, classId.value)
  } catch (e) {
    card.value = null
    const err = e as ApiError
    if (err.status === 403) forbidden.value = err.detail || '无权查看该班级成绩单'
    else message.error(err.detail || '班级成绩单加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  loading.value = true
  try {
    exam.value = await getExam(examId)
    classes.value = await listClassUnits(exam.value.semester_id)
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
          v-model:value="classId" :options="classOptions" clearable
          placeholder="选择班级" style="width: 200px"
          data-testid="report-class-select" @update:value="reloadCard"
        />
        <n-button type="primary" :disabled="!card" data-testid="report-class-print-btn" @click="doPrint">打印</n-button>
      </n-space>
    </div>
    <n-text depth="3" class="no-print" style="font-size: 12px; display: block; margin-bottom: 12px">
      班级成绩单为班主任版,含总分与排名,供班主任核对和存档;只显示所选班级的学生。
    </n-text>

    <h1 v-if="exam" class="head">{{ exam.name }} · 班级成绩单</h1>
    <h2 v-if="card" class="subhead">{{ card.class_name }} · 共 {{ card.students.length }} 人</h2>
    <p v-if="loading" class="empty">载入中…</p>
    <n-text v-else-if="forbidden" type="error" data-testid="report-class-forbidden" style="display: block; text-align: center">{{ forbidden }}</n-text>
    <n-empty v-else-if="!card" description="请先选择班级" />
    <n-empty v-else-if="card.students.length === 0" description="该班级暂无参试学生" />
    <table v-else class="grid">
      <thead>
        <tr>
          <th>学号</th><th>姓名</th>
          <th v-for="s in subjects" :key="s.subject_id">{{ s.subject_name }}</th>
          <th>总分</th><th>班级排名</th><th>年级排名</th><th class="no-print">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="st in card.students" :key="st.student_id">
          <td>{{ st.student_no }}</td>
          <td>{{ st.student_name }}</td>
          <td v-for="s in st.subjects" :key="s.subject_id">
            {{ s.status === '正常' ? formatScore(s.score) : s.status }}
          </td>
          <td>{{ formatScore(st.total) }}</td>
          <td>{{ st.class_rank ?? '—' }}</td>
          <td>{{ st.grade_rank ?? '—' }}</td>
          <td class="no-print"><n-button size="small" text type="primary" @click="goStudentCard(st.student_id)">个人成绩单</n-button></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.sheet {
  max-width: 960px;
  margin: 0 auto;
  padding: 24px;
  color: #000;
  background: #fff;
  font-family: "Microsoft YaHei", "Microsoft JhengHei", "PingFang SC", "PingFang TC", sans-serif;
}
.toolbar { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; }
.head { text-align: center; font-size: 19px; font-weight: 600; letter-spacing: 2px; margin: 0 0 8px; }
.subhead { text-align: center; font-size: 15px; font-weight: 600; margin: 0 0 16px; }
.grid { border-collapse: collapse; width: 100%; table-layout: fixed; font-size: 13px; }
.grid th, .grid td { border: 1px solid #000; padding: 5px 6px; text-align: center; }
.grid th { background: #eee; }
.empty { text-align: center; padding: 40px 0; font-size: 15px; }

@media print {
  @page { size: A4 landscape; margin: 12mm; }
  .no-print { display: none !important; }
  .sheet { max-width: none; padding: 0; }
}
</style>

<style>
/* 打印页套在 MainLayout 内:打印时隐藏侧边栏与顶栏,只留本页内容。 */
@media print {
  .n-layout-sider, .app-header { display: none !important; }
}
</style>
