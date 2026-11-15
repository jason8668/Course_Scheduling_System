<script setup lang="ts">
import {
  NAlert, NButton, NDataTable, NEmpty, NInput, NModal, NPagination,
  NSelect, NSpace, NText, useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { computed, h, onMounted, ref, watch } from 'vue'
import type { ApiError } from '@/api/client'
import {
  CHANGE_TYPES, STUDENT_STATUSES, changeStudentStatus, createStudent,
  exportStudents, getStudent, importStudents, listStatusChanges,
  listStudents, updateStudent, downloadStudentTemplate,
} from '@/api/exam'
import type { ImportResult, StatusChange, Student } from '@/api/exam'
import DingTalkImport from './DingTalkImport.vue'
import { listClassUnits } from '@/api/basedata'
import { listSemesters } from '@/api/semesters'
import type { ClassUnit } from '@/api/basedata'
import type { SemesterListItem } from '@/api/semesters'
import { classLabel } from '@/utils/labels'
import { useAuthStore } from '@/stores/auth'

const message = useMessage()
const auth = useAuthStore()
// 学生写操作只限 admin/director(后端 writer + can_manage_students);
// 越权时后端回 403,前端原样展示后端提示。
const canManage = computed(() => auth.hasRole('admin') || auth.hasRole('director'))

const semesters = ref<SemesterListItem[]>([])
const semesterId = ref<number | null>(null)
const classes = ref<ClassUnit[]>([])
const semesterOptions = computed(() =>
  semesters.value.map((s) => ({ label: s.label, value: s.id })),
)
const gradeOptions = computed(() => {
  const grades = [...new Set(classes.value.map((c) => c.grade))].sort((a, b) => a - b)
  return grades.map((g) => ({ label: `${g} 年级`, value: g }))
})
const classOptions = computed(() =>
  classes.value
    .filter((c) => filterGrade.value == null || c.grade === filterGrade.value)
    .map((c) => ({ label: classLabel(c), value: c.id })),
)
const formClassOptions = computed(() =>
  classes.value.map((c) => ({ label: classLabel(c), value: c.id })),
)

const filterGrade = ref<number | null>(null)
const filterClass = ref<number | null>(null)
const filterQ = ref('')
const filterStatus = ref<string | null>(null)
const statusOptions = STUDENT_STATUSES.map((s) => ({ label: s, value: s }))

const items = ref<Student[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const forbidden = ref(false)

async function reload() {
  if (!semesterId.value) return
  loading.value = true
  forbidden.value = false
  try {
    const res = await listStudents({
      semesterId: semesterId.value,
      grade: filterGrade.value,
      classUnitId: filterClass.value,
      q: filterQ.value || undefined,
      status: filterStatus.value,
      limit: pageSize.value,
      offset: (page.value - 1) * pageSize.value,
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
  classes.value = await listClassUnits(semesterId.value)
  filterGrade.value = null
  filterClass.value = null
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

// ── 新增/编辑 ──
const showForm = ref(false)
const editingId = ref<number | null>(null)
const form = ref({
  class_unit_id: null as number | null,
  student_no: '',
  name: '',
  gender: null as string | null,
  status: '在读',
  exam_no: '',
})
const genderOptions = [
  { label: '男', value: '男' },
  { label: '女', value: '女' },
]
function openCreate() {
  editingId.value = null
  form.value = { class_unit_id: null, student_no: '', name: '', gender: null, status: '在读', exam_no: '' }
  showForm.value = true
}
function openEdit(s: Student) {
  editingId.value = s.id
  form.value = {
    class_unit_id: s.class_unit_id, student_no: s.student_no, name: s.name,
    gender: s.gender, status: s.status, exam_no: s.exam_no ?? '',
  }
  showForm.value = true
}
async function saveForm() {
  if (!semesterId.value) return
  if (!form.value.class_unit_id) { message.warning('请选择班级'); return }
  if (!form.value.student_no.trim()) { message.warning('请输入学号'); return }
  if (!form.value.name.trim()) { message.warning('请输入姓名'); return }
  try {
    if (editingId.value) {
      await updateStudent(editingId.value, {
        name: form.value.name.trim(),
        gender: form.value.gender,
        class_unit_id: form.value.class_unit_id,
      })
    } else {
      await createStudent({
        semester_id: semesterId.value,
        class_unit_id: form.value.class_unit_id,
        student_no: form.value.student_no.trim(),
        name: form.value.name.trim(),
        gender: form.value.gender,
        status: form.value.status,
        exam_no: form.value.exam_no.trim() || null,
      })
    }
    showForm.value = false
    message.success('已储存')
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '储存失败')
  }
}

// ── 详情:异动记录 ──
const showDetail = ref(false)
const detail = ref<Student | null>(null)
const detailChanges = ref<StatusChange[]>([])
const detailForbidden = ref(false)
async function openDetail(s: Student) {
  detailForbidden.value = false
  showDetail.value = true
  try {
    const [st, changes] = await Promise.all([
      getStudent(s.id),
      listStatusChanges(s.id),
    ])
    detail.value = st
    detailChanges.value = changes.items
  } catch (e) {
    if ((e as ApiError).status === 403) detailForbidden.value = true
    else message.error((e as ApiError).detail || '加载失败')
  }
}
// ── 状态变更/异动 ──
const showStatus = ref(false)
const statusForm = ref({
  to_status: '在读',
  change_type: null as string | null,
  note: '',
  new_class_unit_id: null as number | null,
})
const changeTypeOptions = CHANGE_TYPES.map((t) => ({ label: t, value: t }))
function openStatus(s: Student) {
  detail.value = s
  statusForm.value = { to_status: s.status, change_type: null, note: '', new_class_unit_id: null }
  showStatus.value = true
}
async function saveStatus() {
  if (!detail.value) return
  try {
    await changeStudentStatus(detail.value.id, {
      to_status: statusForm.value.to_status,
      note: statusForm.value.note.trim() || null,
      new_class_unit_id: statusForm.value.new_class_unit_id,
      change_type: statusForm.value.change_type,
    })
    showStatus.value = false
    message.success('状态已变更')
    await reload()
    if (showDetail.value) await openDetail(detail.value)
  } catch (e) {
    message.error((e as ApiError).detail || '状态变更失败')
  }
}

// ── 导入导出 ──
const fileInput = ref<HTMLInputElement | null>(null)
const showImportResult = ref(false)
const importResult = ref<ImportResult | null>(null)
const showDingTalkImport = ref(false)
async function onImportFile(ev: Event) {
  const file = (ev.target as HTMLInputElement).files?.[0]
  if (!file || !semesterId.value) return
  try {
    importResult.value = await importStudents(semesterId.value, file)
    showImportResult.value = true
    message.success(`导入完成:新增 ${importResult.value.created} 人,更新 ${importResult.value.updated} 人`)
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || (e as Error).message || '导入失败')
  } finally {
    if (fileInput.value) fileInput.value.value = ''
  }
}
async function onDownloadTemplate() {
  try {
    await downloadStudentTemplate()
  } catch (e) {
    message.error((e as Error).message || '模板下载失败')
  }
}
async function onExport() {
  if (!semesterId.value) return
  try {
    await exportStudents(semesterId.value, filterGrade.value, filterClass.value)
    message.success('已导出')
  } catch (e) {
    message.error((e as Error).message || '导出失败')
  }
}

const columns: DataTableColumns<Student> = [
  { title: '学号', key: 'student_no', width: 110 },
  {
    title: '姓名',
    key: 'name',
    render: (row) => h(
      NButton,
      { text: true, type: 'primary', onClick: () => openDetail(row) },
      () => row.name,
    ),
  },
  { title: '性别', key: 'gender', width: 60, render: (row) => row.gender ?? '—' },
  { title: '年级', key: 'grade', width: 80, render: (row) => row.grade != null ? `${row.grade}年级` : '—' },
  { title: '班级', key: 'class_name', render: (row) => row.class_name || '—' },
  {
    title: '状态',
    key: 'status',
    width: 80,
    render: (row) => row.status,
  },
  { title: '考号', key: 'exam_no', width: 110, render: (row) => row.exam_no ?? '—' },
  {
    title: '操作',
    key: 'actions',
    width: 190,
    render: (row) => h(NSpace, { size: 'small' }, {
      default: () => [
        h(NButton, { size: 'small', text: true, type: 'primary', onClick: () => openDetail(row) }, () => '详情'),
        ...(canManage.value ? [
          h(NButton, { size: 'small', text: true, type: 'primary', onClick: () => openEdit(row) }, () => '编辑'),
          h(NButton, { size: 'small', text: true, onClick: () => openStatus(row) }, () => '状态变更'),
        ] : []),
      ],
    }),
  },
]
</script>

<template>
  <div class="ios-page">
    <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap">
      <h1 class="ios-title">学生档案</h1>
      <n-select
        v-model:value="semesterId"
        :options="semesterOptions"
        placeholder="选择学期"
        style="width: 240px"
      />
    </div>

    <n-alert v-if="!semesterId" type="info" style="margin-top: 16px">
      请先建立学期,再回此页维护学生档案。
    </n-alert>
    <n-alert v-else-if="forbidden" type="error" style="margin-top: 16px" data-testid="students-forbidden">
      无权查看学生档案(不在你的可见范围内)。
    </n-alert>

    <template v-else>
      <div class="ios-card" style="margin-top: 16px">
        <div class="ios-card-body">
          <n-space :wrap="true" align="center">
            <n-select
              v-model:value="filterGrade" :options="gradeOptions" clearable
              placeholder="年级" style="width: 120px" @update:value="onFilterChange"
            />
            <n-select
              v-model:value="filterClass" :options="classOptions" clearable
              placeholder="班级" style="width: 160px" @update:value="onFilterChange"
            />
            <n-select
              v-model:value="filterStatus" :options="statusOptions" clearable
              placeholder="状态" style="width: 120px" @update:value="onFilterChange"
            />
            <n-input
              v-model:value="filterQ" placeholder="按姓名或学号检索" clearable
              style="width: 200px" @change="onFilterChange"
            />
            <n-button type="primary" @click="onFilterChange">检索</n-button>
          </n-space>
          <n-space :wrap="true" style="margin-top: 12px">
            <n-button v-if="canManage" type="primary" @click="openCreate">新增学生</n-button>
            <n-button v-if="canManage" @click="onDownloadTemplate">下载导入模板</n-button>
            <n-button v-if="canManage" @click="fileInput?.click()">批量导入</n-button>
            <input ref="fileInput" type="file" accept=".xlsx,.xls" style="display: none" @change="onImportFile">
            <n-button v-if="canManage" @click="showDingTalkImport = true">从钉钉导入</n-button>
            <n-button @click="onExport">导出学生名单</n-button>
          </n-space>
        </div>
      </div>

      <div class="ios-card" style="margin-top: 16px">
        <div class="ios-card-body">
          <n-empty v-if="!loading && items.length === 0" description="没有符合条件的学生" />
          <n-data-table
            v-else :columns="columns" :data="items" :loading="loading"
            :bordered="false" :single-line="false"
          />
          <div style="margin-top: 12px; display: flex; justify-content: flex-end">
            <n-pagination
              v-model:page="page" v-model:page-size="pageSize" :item-count="total"
              :page-sizes="[20, 50, 100]" show-size-picker @update:page="reload" @update:page-size="reload"
            />
          </div>
          <n-text depth="3" style="font-size: 13px">共 {{ total }} 人</n-text>
        </div>
      </div>
    </template>

    <!-- 每行点姓名或「详情」进详情页;编辑与状态变更在列表操作列与详情页都能操作。 -->
    <n-modal v-model:show="showDetail" preset="card" title="学生详情" style="max-width: 640px">
      <n-alert v-if="detailForbidden" type="error">无权查看该学生(不在你的可见范围内)。</n-alert>
      <template v-else-if="detail">
        <n-space vertical>
          <div>
            <div class="ios-row-title">{{ detail.name }} · {{ detail.student_no }}</div>
            <div class="ios-row-sub">
              {{ detail.grade != null ? `${detail.grade} 年级 ` : '' }}{{ detail.class_name }}
              · {{ detail.gender ?? '性别未填' }} · {{ detail.status }}
              · 考号 {{ detail.exam_no ?? '未编排' }}
            </div>
          </div>
          <n-space>
            <n-button v-if="canManage" size="small" type="primary" @click="openEdit(detail)">编辑档案</n-button>
            <n-button v-if="canManage" size="small" @click="openStatus(detail)">状态变更</n-button>
          </n-space>
          <div>
            <div class="ios-section-title">异动记录</div>
            <n-empty v-if="detailChanges.length === 0" description="暂无异动记录" />
            <div v-for="c in detailChanges" :key="c.id" class="ios-row">
              <div class="ios-row-main">
                <div class="ios-row-title">
                  {{ c.change_type }}: {{ c.from_status ?? '—' }} → {{ c.to_status ?? '—' }}
                </div>
                <div class="ios-row-sub">
                  {{ classLabel({ grade: c.from_grade, name: c.from_class_name }) }} → {{ classLabel({ grade: c.to_grade, name: c.to_class_name }) }}
                  {{ c.note ? ` · ${c.note}` : '' }}
                  {{ c.created_at ? ` · ${c.created_at}` : '' }}
                </div>
              </div>
            </div>
          </div>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showForm" preset="card" :title="editingId ? '编辑学生' : '新增学生'" style="max-width: 480px">
      <n-space vertical>
        <n-text>班级</n-text>
        <n-select v-model:value="form.class_unit_id" :options="formClassOptions" placeholder="选择班级" />
        <n-text>学号</n-text>
        <n-input v-model:value="form.student_no" :disabled="!!editingId" placeholder="学号是唯一标识,建好后不可改" />
        <n-text>姓名</n-text>
        <n-input v-model:value="form.name" placeholder="姓名" />
        <n-text>性别(选填)</n-text>
        <n-select v-model:value="form.gender" :options="genderOptions" clearable placeholder="未填" />
        <n-text v-if="!editingId">状态</n-text>
        <n-select v-if="!editingId" v-model:value="form.status" :options="statusOptions" />
        <n-text v-if="!editingId">考号(选填)</n-text>
        <n-input v-if="!editingId" v-model:value="form.exam_no" placeholder="不填则由考号规则生成" />
        <n-button type="primary" @click="saveForm">储存</n-button>
      </n-space>
    </n-modal>

    <n-modal v-model:show="showStatus" preset="card" title="状态变更" style="max-width: 480px">
      <n-space vertical>
        <n-text>异动类型</n-text>
        <n-select v-model:value="statusForm.change_type" :options="changeTypeOptions" clearable placeholder="选择异动类型" />
        <n-text>变更为</n-text>
        <n-select v-model:value="statusForm.to_status" :options="statusOptions" />
        <n-text v-if="statusForm.change_type === '转班'">新班级</n-text>
        <n-select
          v-if="statusForm.change_type === '转班'"
          v-model:value="statusForm.new_class_unit_id" :options="formClassOptions" placeholder="选择新班级"
        />
        <n-text>备注(选填)</n-text>
        <n-input v-model:value="statusForm.note" type="textarea" placeholder="异动原因或说明" />
        <n-text depth="3" style="font-size: 12px">转班后新考试归新班,历史考试成绩仍归原班。</n-text>
        <n-button type="primary" @click="saveStatus">确认变更</n-button>
      </n-space>
    </n-modal>

    <n-modal v-model:show="showImportResult" preset="card" title="导入结果" style="max-width: 560px">
      <n-space vertical>
        <n-text>新增 {{ importResult?.created ?? 0 }} 人,更新 {{ importResult?.updated ?? 0 }} 人。</n-text>
        <n-alert v-if="importResult && importResult.errors.length" type="warning" title="以下行导入失败,未入库">
          <div v-for="(err, i) in importResult.errors" :key="i" style="font-size: 13px">{{ err }}</div>
        </n-alert>
        <n-text v-else type="success">全部导入成功,无错误行。</n-text>
      </n-space>
    </n-modal>

    <DingTalkImport
      v-if="showDingTalkImport && semesterId" :semester-id="semesterId" :classes="classes"
      @done="showDingTalkImport = false; void reload()"
      @close="showDingTalkImport = false"
    />
  </div>
</template>
