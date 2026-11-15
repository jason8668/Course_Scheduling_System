<script setup lang="ts">
import {
  NAlert, NButton, NDataTable, NEmpty, NInput, NSelect, NSpace, NText, useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { computed, h, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import {
  exportGradeBook, formatScore, getExam,
  listTeacherScores,
} from '@/api/exam'
import type { ExamDetail, TeacherScoreItem } from '@/api/exam'
import { listClassUnits } from '@/api/basedata'
import type { ClassUnit } from '@/api/basedata'
import { classLabel } from '@/utils/labels'
import { useAuthStore } from '@/stores/auth'

// 教师端成绩查询页(KW-54):任课教师查所教班级本科成绩,班主任查本班全部科目成绩,
// 权限按角色自动限定范围(后端按可见范围过滤,越权 403 原样展示)。
// 另含成绩册导出(KW-56)。

const message = useMessage()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const examId = Number(route.params.id)
// 成绩册导出只限 admin/director,越权时后端回 403,前端原样展示。
const canManage = computed(() => auth.hasRole('admin') || auth.hasRole('director'))

const exam = ref<ExamDetail | null>(null)
const classes = ref<ClassUnit[]>([])
const filterSubject = ref<number | null>(null)
const filterClass = ref<number | null>(null)
const filterQ = ref('')
const items = ref<TeacherScoreItem[]>([])
const total = ref(0)
const loading = ref(false)
const forbidden = ref('')

const subjectOptions = computed(() =>
  (exam.value?.subjects ?? []).map((s) => ({ label: s.subject_name, value: s.subject_id })),
)
const classOptions = computed(() =>
  classes.value.map((c) => ({ label: classLabel(c), value: c.id })),
)

const columns: DataTableColumns<TeacherScoreItem> = [
  { title: '学号', key: 'student_no', width: 110 },
  { title: '姓名', key: 'student_name', width: 90 },
  {
    title: '年级', key: 'grade', width: 70,
    render: (row) => (row.grade != null ? `${row.grade}年级` : '—'),
  },
  { title: '班级', key: 'class_name', width: 110 },
  { title: '科目', key: 'subject_name', width: 90 },
  {
    title: '成绩', key: 'score', width: 80,
    render: (row) => (row.status === '正常' ? formatScore(row.score) : row.status),
  },
  { title: '总分', key: 'total', width: 80, render: (row) => formatScore(row.total) },
  { title: '班级排名', key: 'class_rank', width: 90, render: (row) => row.class_rank ?? '—' },
  { title: '年级排名', key: 'grade_rank', width: 90, render: (row) => row.grade_rank ?? '—' },
  {
    title: '操作', key: 'actions', width: 110,
    render: (row) => hAction(row),
  },
]

function hAction(row: TeacherScoreItem) {
  return h(NButton, {
    size: 'small', text: true, type: 'primary',
    onClick: () => goStudentCard(row.student_id),
  }, () => '个人成绩单')
}

function goBack() {
  void router.push({ name: 'exam-exam-detail', params: { id: examId } })
}
function goClassCard() {
  if (!filterClass.value) { message.warning('请先选择班级'); return }
  void router.push({ name: 'exam-exam-report-class', params: { id: examId } })
}
function goStudentCard(studentId: number) {
  void router.push({
    name: 'exam-exam-report-student',
    params: { id: examId },
    query: { student_id: String(studentId) },
  })
}

async function reload() {
  loading.value = true
  forbidden.value = ''
  try {
    const res = await listTeacherScores(examId, {
      subjectId: filterSubject.value,
      classUnitId: filterClass.value,
      q: filterQ.value || undefined,
    })
    items.value = res.items
    total.value = res.total
  } catch (e) {
    items.value = []
    total.value = 0
    const err = e as ApiError
    if (err.status === 403) forbidden.value = err.detail || '无权查询该范围的成绩'
    else message.error(err.detail || '成绩查询失败')
  } finally {
    loading.value = false
  }
}

async function onExportGradeBook() {
  try {
    await exportGradeBook(examId)
    message.success('成绩册已开始下载')
  } catch (e) {
    message.error((e as ApiError).detail || '成绩册导出失败')
  }
}

onMounted(async () => {
  loading.value = true
  try {
    exam.value = await getExam(examId)
    classes.value = await listClassUnits(exam.value.semester_id)
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '加载失败')
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="ios-page">
    <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap">
      <n-button text type="primary" @click="goBack">← 考试详情</n-button>
      <h1 class="ios-title">{{ exam?.name ?? '考试' }} · 成绩查询</h1>
    </div>

    <!-- 成绩查询(KW-54) -->
    <div class="ios-section">
      <div class="ios-section-title">教师端成绩查询</div>
      <div class="ios-card"><div class="ios-card-body">
        <n-space :wrap="true" align="center">
          <n-select
            v-model:value="filterSubject" :options="subjectOptions" clearable
            placeholder="全部科目" style="width: 150px" @update:value="reload"
          />
          <n-select
            v-model:value="filterClass" :options="classOptions" clearable
            placeholder="全部班级" style="width: 170px" @update:value="reload"
          />
          <n-input
            v-model:value="filterQ" placeholder="按姓名或学号检索" clearable
            style="width: 200px" @change="reload"
          />
          <n-button type="primary" data-testid="teacher-scores-search" @click="reload">检索</n-button>
          <n-button data-testid="teacher-scores-class-card" @click="goClassCard">班级成绩单</n-button>
          <n-button
            v-if="canManage" data-testid="teacher-scores-export-grade-book"
            @click="onExportGradeBook"
          >导出成绩册 Excel</n-button>
        </n-space>
        <n-text depth="3" style="font-size: 12px; display: block; margin-top: 8px">
          任课教师只看所教班级本科成绩,班主任看本班全部科目成绩;范围由后端按角色自动限定,越权会原样提示。
        </n-text>
        <n-alert
          v-if="forbidden" type="error" style="margin-top: 12px"
          data-testid="teacher-scores-forbidden"
        >{{ forbidden }}</n-alert>
        <n-empty v-else-if="!loading && items.length === 0" description="暂无成绩,请先调整筛选或确认成绩已发布" style="margin-top: 12px" />
        <n-data-table
          v-else :columns="columns" :data="items" :loading="loading"
          :bordered="false" :single-line="false" style="margin-top: 12px"
        />
        <n-text depth="3" style="font-size: 13px">共 {{ total }} 条</n-text>
      </div></div>
    </div>

  </div>
</template>
