<script setup lang="ts">
import {
  NAlert, NButton, NDataTable, NEmpty, NInput, NModal, NPagination, NSpace, NSelect, NText,
  useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { computed, h, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import {
  EXAM_STATUSES, EXAM_TYPES, copyExam, createExam, listExams,
} from '@/api/exam'
import type { Exam } from '@/api/exam'
import { listClassUnits } from '@/api/basedata'
import { listSemesters } from '@/api/semesters'
import type { SemesterListItem } from '@/api/semesters'
import { useAuthStore } from '@/stores/auth'

const message = useMessage()
const auth = useAuthStore()
const router = useRouter()
// 考试管理是教务职责:写操作只限 admin/director,越权时后端回 403,前端原样展示。
const canManage = computed(() => auth.hasRole('admin') || auth.hasRole('director'))

const semesters = ref<SemesterListItem[]>([])
const semesterId = ref<number | null>(null)
const semesterOptions = computed(() =>
  semesters.value.map((s) => ({ label: s.label, value: s.id })),
)
const gradeOptions = ref<{ label: string; value: number }[]>([])

const filterStatus = ref<string | null>(null)
const filterQ = ref('')
const statusOptions = EXAM_STATUSES.map((s) => ({ label: s, value: s }))

const items = ref<Exam[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const forbidden = ref(false)

// 契约只给 semester_id/status/q 三个检索参数,不带分页参数:
// 后端返回全量后前端按页切分,不擅自给契约加 limit/offset。
const pageItems = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return items.value.slice(start, start + pageSize.value)
})

async function reload() {
  loading.value = true
  forbidden.value = false
  try {
    const res = await listExams({
      semesterId: semesterId.value,
      status: filterStatus.value,
      q: filterQ.value || undefined,
    })
    items.value = res.items
    total.value = res.total
  } catch (e) {
    if ((e as ApiError).status === 403) forbidden.value = true
    else message.error((e as ApiError).detail || '加载失败')
  } finally {
    loading.value = false
  }
}

function onFilterChange() {
  page.value = 1
  void reload()
}

async function loadSemesterData() {
  if (!semesterId.value) return
  try {
    const classes = await listClassUnits(semesterId.value)
    const grades = [...new Set(classes.map((c) => c.grade))].sort((a, b) => a - b)
    gradeOptions.value = (grades.length ? grades : [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])
      .map((g) => ({ label: `${g} 年级`, value: g }))
  } catch {
    gradeOptions.value = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
      .map((g) => ({ label: `${g} 年级`, value: g }))
  }
  page.value = 1
  await reload()
}

onMounted(async () => {
  try {
    semesters.value = await listSemesters()
    if (semesters.value.length) {
      semesterId.value = semesters.value[0].id
      await loadSemesterData()
    }
  } catch (e) {
    message.error((e as ApiError).detail || '学期加载失败')
  }
})
watch(semesterId, (v, old) => {
  if (v && v !== old) void loadSemesterData()
})

function openDetail(row: Exam) {
  void router.push({ name: 'exam-exam-detail', params: { id: row.id } })
}

// ── 新建考试(KW-08) ──
const showForm = ref(false)
const form = ref({
  semester_id: null as number | null,
  name: '',
  exam_type: '月考',
  grades: [] as number[],
  description: '',
})
const typeOptions = EXAM_TYPES.map((t) => ({ label: t, value: t }))
function openCreate() {
  form.value = {
    semester_id: semesterId.value, name: '', exam_type: '月考', grades: [], description: '',
  }
  showForm.value = true
}
async function saveForm() {
  if (!form.value.semester_id) { message.warning('请选择学期'); return }
  if (!form.value.name.trim()) { message.warning('请输入考试名称'); return }
  if (!form.value.grades.length) { message.warning('请至少选择一个参试年级'); return }
  try {
    await createExam({
      semester_id: form.value.semester_id,
      name: form.value.name.trim(),
      exam_type: form.value.exam_type,
      grades: form.value.grades,
      description: form.value.description.trim() || null,
    })
    showForm.value = false
    message.success('考试已创建(草稿)')
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '创建失败')
  }
}

// ── 复制考试(KW-12):复制科目、分值、日程结构与编排规则,新考试为草稿 ──
const showCopy = ref(false)
const copyTarget = ref<Exam | null>(null)
const copyForm = ref({ name: '', semester_id: null as number | null })
function openCopy(row: Exam) {
  copyTarget.value = row
  copyForm.value = { name: `${row.name}(复制)`, semester_id: row.semester_id }
  showCopy.value = true
}
async function saveCopy() {
  if (!copyTarget.value || !copyForm.value.semester_id) return
  if (!copyForm.value.name.trim()) { message.warning('请输入新考试名称'); return }
  try {
    await copyExam(copyTarget.value.id, {
      name: copyForm.value.name.trim(),
      semester_id: copyForm.value.semester_id,
    })
    showCopy.value = false
    message.success('已复制为草稿')
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '复制失败')
  }
}

const columns: DataTableColumns<Exam> = [
  {
    title: '考试名称',
    key: 'name',
    render: (row) => h(
      NButton,
      { text: true, type: 'primary', onClick: () => openDetail(row) },
      () => row.name,
    ),
  },
  { title: '类型', key: 'exam_type', width: 80 },
  {
    title: '参试年级',
    key: 'grades',
    render: (row) => row.grades.map((g) => `${g} 年级`).join('、') || '—',
  },
  { title: '状态', key: 'status', width: 110 },
  {
    title: '创建时间',
    key: 'created_at',
    width: 170,
    render: (row) => row.created_at ?? '—',
  },
  {
    title: '操作',
    key: 'actions',
    width: 140,
    render: (row) => h(NSpace, { size: 'small' }, {
      default: () => [
        h(NButton, { size: 'small', text: true, type: 'primary', onClick: () => openDetail(row) }, () => '详情'),
        ...(canManage.value ? [
          h(NButton, { size: 'small', text: true, onClick: () => openCopy(row) }, () => '复制'),
        ] : []),
      ],
    }),
  },
]
</script>

<template>
  <div class="ios-page">
    <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap">
      <h1 class="ios-title">考试管理</h1>
      <n-select
        v-model:value="semesterId"
        :options="semesterOptions"
        placeholder="选择学期"
        style="width: 240px"
      />
    </div>

    <n-alert v-if="!semesterId" type="info" style="margin-top: 16px">
      请先建立学期,再回此页管理考试。
    </n-alert>
    <n-alert v-else-if="forbidden" type="error" style="margin-top: 16px" data-testid="exams-forbidden">
      无权查看考试(不在你的可见范围内)。
    </n-alert>

    <template v-else>
      <div class="ios-card" style="margin-top: 16px">
        <div class="ios-card-body">
          <n-space :wrap="true" align="center">
            <n-select
              v-model:value="filterStatus" :options="statusOptions" clearable
              placeholder="状态" style="width: 140px" @update:value="onFilterChange"
            />
            <n-input
              v-model:value="filterQ" placeholder="按考试名称检索" clearable
              style="width: 220px" @change="onFilterChange"
            />
            <n-button type="primary" @click="onFilterChange">检索</n-button>
            <n-button v-if="canManage" type="primary" @click="openCreate">新建考试</n-button>
          </n-space>
          <n-text depth="3" style="font-size: 13px; display: block; margin-top: 8px">
            点考试名称或「详情」进入一次考试的管理页;复制沿用上一次同类考试的科目、日程结构与编排规则,改日期即可快速建考。
          </n-text>
        </div>
      </div>

      <div class="ios-card" style="margin-top: 16px">
        <div class="ios-card-body">
          <n-empty v-if="!loading && items.length === 0" description="没有符合条件的考试" />
          <n-data-table
            v-else :columns="columns" :data="pageItems" :loading="loading"
            :bordered="false" :single-line="false"
          />
          <div style="margin-top: 12px; display: flex; justify-content: flex-end">
            <n-pagination
              v-model:page="page" v-model:page-size="pageSize" :item-count="total"
              :page-sizes="[20, 50, 100]" show-size-picker
              @update:page="() => {}" @update:page-size="() => { page = 1 }"
            />
          </div>
          <n-text depth="3" style="font-size: 13px">共 {{ total }} 场考试</n-text>
        </div>
      </div>
    </template>

    <n-modal v-model:show="showForm" preset="card" title="新建考试" style="max-width: 480px">
      <n-space vertical>
        <n-text>学期</n-text>
        <n-select v-model:value="form.semester_id" :options="semesterOptions" placeholder="选择学期" />
        <n-text>考试名称</n-text>
        <n-input v-model:value="form.name" placeholder="如:2026 学年第一学期期中考试" />
        <n-text>考试类型</n-text>
        <n-select v-model:value="form.exam_type" :options="typeOptions" />
        <n-text>参试年级(多选)</n-text>
        <n-select v-model:value="form.grades" :options="gradeOptions" multiple placeholder="选择参试年级" />
        <n-text>考试说明(选填)</n-text>
        <n-input v-model:value="form.description" type="textarea" placeholder="考试说明" />
        <n-text depth="3" style="font-size: 12px">新建的考试为草稿状态,可反复修改;发布后按状态流转推进。</n-text>
        <n-button type="primary" @click="saveForm">创建草稿</n-button>
      </n-space>
    </n-modal>

    <n-modal v-model:show="showCopy" preset="card" title="复制考试" style="max-width: 480px">
      <n-space vertical>
        <n-text>新考试名称</n-text>
        <n-input v-model:value="copyForm.name" placeholder="新考试名称" />
        <n-text>学期</n-text>
        <n-select v-model:value="copyForm.semester_id" :options="semesterOptions" placeholder="选择学期" />
        <n-text depth="3" style="font-size: 12px">
          复制沿用原考试的科目、分值、日程结构与编排规则,新考试为草稿,日程日期请在详情页修改。
        </n-text>
        <n-button type="primary" @click="saveCopy">复制为草稿</n-button>
      </n-space>
    </n-modal>
  </div>
</template>
