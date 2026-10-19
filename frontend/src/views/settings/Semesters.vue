<script setup lang="ts">
import {
  NButton, NCard, NCheckbox, NDatePicker, NDivider, NEmpty, NInputNumber, NModal,
  NPopconfirm, NSelect, NSpace, NSwitch, NTag, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import {
  STATUS_LABELS, copySemester, createPeriodTable, createSemester, deletePeriodTable,
  deleteSemester, listSemesters, listTemplates, updateSemester,
} from '@/api/semesters'
import type { CopyOptions, SemesterListItem, Semester, Template } from '@/api/semesters'
import { getSemester } from '@/api/semesters'

const message = useMessage()
const router = useRouter()

const semesters = ref<Semester[]>([])
const templates = ref<Template[]>([])
const loading = ref(false)

// 建立学期表单。起讫日期是请假展开、今日看板、调代课判定的依据——少了它请假会被挡,
// 而先前界面上没有任何地方填得了(用户回报 #15)
const emptyForm = () => ({
  academic_year: 115, term: 1, template_key: null as string | null,
  start_date: null as string | null, end_date: null as string | null,
})
const form = ref(emptyForm())
const templateOptions = computed(() => [
  { label: '空白(不带入节次表)', value: '' },
  ...templates.value.map((t) => ({ label: `${t.name}(${t.minutes_per_period} 分/节)`, value: t.key })),
])
const termOptions = [
  { label: '第 1 学期', value: 1 },
  { label: '第 2 学期', value: 2 },
]

async function reload() {
  loading.value = true
  try {
    const items = await listSemesters()
    // 逐一取回含节次表的完整资料
    semesters.value = await Promise.all(items.map((s: SemesterListItem) => getSemester(s.id)))
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  templates.value = await listTemplates()
  await reload()
})

async function onCreateSemester() {
  if (!form.value.start_date || !form.value.end_date) {
    message.warning('请填学期起讫日期(请假与调代课需要)')
    return
  }
  try {
    await createSemester({
      academic_year: form.value.academic_year,
      term: form.value.term,
      template_key: form.value.template_key || null,
      start_date: form.value.start_date,
      end_date: form.value.end_date,
    })
    message.success('学期已建立')
    form.value = emptyForm()
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '建立失败')
  }
}

// 编辑学期:已经建好、但没有起讫日期的学期靠这里补(先前只能重建或改资料库)
const showEdit = ref(false)
const editing = ref<Semester | null>(null)
const editForm = ref({ start_date: null as string | null, end_date: null as string | null })

function openEdit(sem: Semester) {
  editing.value = sem
  editForm.value = { start_date: sem.start_date, end_date: sem.end_date }
  showEdit.value = true
}

async function onSaveEdit() {
  if (!editing.value) return
  if (!editForm.value.start_date || !editForm.value.end_date) {
    message.warning('请填学期起讫日期')
    return
  }
  try {
    await updateSemester(editing.value.id, {
      start_date: editForm.value.start_date,
      end_date: editForm.value.end_date,
    })
    message.success('学期已更新')
    showEdit.value = false
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '更新失败')
  }
}

async function onDeleteSemester(id: number) {
  await deleteSemester(id)
  message.success('学期已删除')
  await reload()
}

// 新增节次表 modal
const showAddTable = ref(false)
const addTableTarget = ref<number | null>(null)
const addTableForm = ref({ name: '', template_key: null as string | null, is_default: false })

function openAddTable(semesterId: number) {
  addTableTarget.value = semesterId
  addTableForm.value = { name: '', template_key: null, is_default: false }
  showAddTable.value = true
}

async function onAddTable() {
  if (!addTableForm.value.name) {
    message.warning('请输入节次表名称')
    return
  }
  try {
    await createPeriodTable(addTableTarget.value!, {
      name: addTableForm.value.name,
      template_key: addTableForm.value.template_key || null,
      is_default: addTableForm.value.is_default,
    })
    showAddTable.value = false
    message.success('节次表已新增')
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '新增失败')
  }
}

async function onDeleteTable(id: number) {
  await deletePeriodTable(id)
  message.success('节次表已删除')
  await reload()
}

function editTable(id: number) {
  router.push({ name: 'period-table-editor', params: { id } })
}

// 复制到新学期
const showCopy = ref(false)
const copySource = ref<Semester | null>(null)

/** 来源日期往后推半年,作为新学期的默认值(用户仍须依实际校历确认)。 */
function halfYearLater(day: string | null): string | null {
  if (!day) return null
  const d = new Date(day)
  d.setMonth(d.getMonth() + 6)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

const emptyCopyForm = (): CopyOptions => ({
  academic_year: 115, term: 1,
  start_date: null, end_date: null,
  period_tables: true, subjects: true, teachers: true, rooms: true, classes: true,
  grade_promotion: true, constraint_config: true,
})
const copyForm = ref<CopyOptions>(emptyCopyForm())

function openCopy(sem: Semester) {
  copySource.value = sem
  copyForm.value = {
    ...emptyCopyForm(),
    academic_year: sem.academic_year + 1,
    term: sem.term,
    // 起讫日不可沿用来源(那是上学期的日期);往后推半年带个起点,让组长改而不是从零填
    start_date: halfYearLater(sem.start_date),
    end_date: halfYearLater(sem.end_date),
  }
  showCopy.value = true
}

async function onCopy() {
  if (!copySource.value) return
  try {
    await copySemester(copySource.value.id, copyForm.value)
    showCopy.value = false
    message.success('已复制到新学期')
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '复制失败')
  }
}

const statusType: Record<string, 'default' | 'success' | 'warning'> = {
  preparing: 'warning',
  active: 'success',
  archived: 'default',
}
</script>

<template>
  <div>
    <n-space vertical size="large">
      <h1 style="margin: 0">学期与节次表</h1>

      <n-card title="建立学期">
        <n-space align="center" :wrap="true">
          <n-text>学年度</n-text>
          <n-input-number v-model:value="form.academic_year" :min="100" :max="200" style="width: 120px" />
          <n-select v-model:value="form.term" :options="termOptions" style="width: 130px" />
          <n-text>学制范本</n-text>
          <n-select
            v-model:value="form.template_key"
            :options="templateOptions"
            placeholder="选择学制范本"
            style="width: 220px"
          />
          <n-text>起讫日期</n-text>
          <n-date-picker
            v-model:formatted-value="form.start_date" value-format="yyyy-MM-dd"
            type="date" placeholder="开学日" style="width: 150px" data-testid="sem-start"
          />
          <n-text>~</n-text>
          <n-date-picker
            v-model:formatted-value="form.end_date" value-format="yyyy-MM-dd"
            type="date" placeholder="结业日" style="width: 150px" data-testid="sem-end"
          />
          <n-button type="primary" data-testid="sem-create" @click="onCreateSemester">建立</n-button>
        </n-space>
        <n-text depth="3" style="font-size: 13px">
          起讫日期依贵校校历填写;请假展开节次、今日看板与调代课都以它为准。
        </n-text>
      </n-card>

      <n-empty v-if="!loading && semesters.length === 0" description="尚未建立任何学期" />

      <n-card v-for="sem in semesters" :key="sem.id">
        <n-space justify="space-between" align="center">
          <n-space align="center">
            <strong>{{ sem.label }}</strong>
            <n-tag :type="statusType[sem.status]" size="small">{{ STATUS_LABELS[sem.status] }}</n-tag>
            <n-text v-if="sem.start_date && sem.end_date" depth="3" data-testid="sem-range">
              {{ sem.start_date }} ~ {{ sem.end_date }}
            </n-text>
            <n-tag v-else type="warning" size="small" data-testid="sem-no-range">
              尚未设置起讫日期(无法登记请假)
            </n-tag>
          </n-space>
          <n-space>
            <n-button size="tiny" data-testid="sem-edit" @click="openEdit(sem)">编辑学期</n-button>
            <n-button size="tiny" data-testid="copy-semester" @click="openCopy(sem)">
              复制到新学期
            </n-button>
            <n-popconfirm @positive-click="onDeleteSemester(sem.id)">
              <template #trigger>
                <n-button size="tiny" type="error" ghost>删除学期</n-button>
              </template>
              确定删除此学期?其节次表将一并移除。
            </n-popconfirm>
          </n-space>
        </n-space>

        <n-divider style="margin: 12px 0" />

        <n-space vertical size="small">
          <n-space
            v-for="table in sem.period_tables"
            :key="table.id"
            align="center"
            justify="space-between"
          >
            <n-space align="center">
              <n-text>{{ table.name }}</n-text>
              <n-tag v-if="table.is_default" type="success" size="tiny">默认</n-tag>
              <n-text depth="3">共 {{ table.periods.length }} 格</n-text>
            </n-space>
            <n-space>
              <n-button size="tiny" @click="editTable(table.id)">编辑节次表</n-button>
              <n-popconfirm @positive-click="onDeleteTable(table.id)">
                <template #trigger>
                  <n-button size="tiny" type="error" ghost>删除</n-button>
                </template>
                确定删除此节次表?
              </n-popconfirm>
            </n-space>
          </n-space>
          <n-button size="small" dashed @click="openAddTable(sem.id)">+ 新增节次表</n-button>
        </n-space>
      </n-card>
    </n-space>

    <!-- 视窗放在排版容器外面:n-space 会把每个子节点包一层没有 key 的 div,
         学期卡片数量一变(载入完成、新增、删除)视窗就跟著换位置重挂,
         正式建置下会变成关不掉(X、Esc、点视窗外都没反应)。 -->
    <n-modal
      v-model:show="showEdit" preset="card" style="max-width: 420px"
      :title="`编辑学期:${editing?.label ?? ''}`"
    >
      <n-space vertical size="small">
        <n-text>学期起讫日期</n-text>
        <n-space align="center">
          <n-date-picker
            v-model:formatted-value="editForm.start_date" value-format="yyyy-MM-dd"
            type="date" placeholder="开学日" style="width: 150px" data-testid="sem-edit-start"
          />
          <n-text>~</n-text>
          <n-date-picker
            v-model:formatted-value="editForm.end_date" value-format="yyyy-MM-dd"
            type="date" placeholder="结业日" style="width: 150px" data-testid="sem-edit-end"
          />
        </n-space>
        <n-text depth="3" style="font-size: 13px">
          请假只能登记在这个范围内;改动不影响已排好的课表。
        </n-text>
        <n-button type="primary" data-testid="sem-edit-save" @click="onSaveEdit">储存</n-button>
      </n-space>
    </n-modal>

    <n-modal
      v-model:show="showAddTable"
      preset="card"
      title="新增节次表"
      style="max-width: 440px"
    >
      <n-space vertical>
        <n-text>名称</n-text>
        <n-select
          v-model:value="addTableForm.name"
          filterable
          tag
          :options="[
            { label: '高中部节次表', value: '高中部节次表' },
            { label: '初中部节次表', value: '初中部节次表' },
          ]"
          placeholder="输入或选择名称"
        />
        <n-text>带入学制范本(选填)</n-text>
        <n-select
          v-model:value="addTableForm.template_key"
          :options="templateOptions"
          placeholder="不带入则建立空表"
        />
        <n-button type="primary" @click="onAddTable">建立</n-button>
      </n-space>
    </n-modal>

    <n-modal
      v-model:show="showCopy"
      preset="card"
      :title="`复制「${copySource?.label}」到新学期`"
      style="max-width: 460px"
    >
      <n-space vertical>
        <n-space align="center">
          <n-text>目标学年度</n-text>
          <n-input-number v-model:value="copyForm.academic_year" :min="100" :max="200" style="width: 120px" />
          <n-select v-model:value="copyForm.term" :options="termOptions" style="width: 130px" />
        </n-space>
        <!-- 起讫日必填:请假展开、今日看板、代课的「已上过」判定都吃它,漏填不会报错但整个算错 -->
        <n-space align="center">
          <n-text>学期起讫</n-text>
          <n-date-picker
            v-model:formatted-value="copyForm.start_date" value-format="yyyy-MM-dd"
            type="date" data-testid="copy-start" style="width: 150px"
          />
          <n-text>~</n-text>
          <n-date-picker
            v-model:formatted-value="copyForm.end_date" value-format="yyyy-MM-dd"
            type="date" data-testid="copy-end" style="width: 150px"
          />
        </n-space>
        <n-text depth="3" style="font-size: 12px">
          已依来源学期往后推半年带入默认值,请确认实际校历后修改。
        </n-text>
        <n-text strong>复制项目</n-text>
        <n-space>
          <n-checkbox v-model:checked="copyForm.period_tables">节次表</n-checkbox>
          <n-checkbox v-model:checked="copyForm.subjects">科目</n-checkbox>
          <n-checkbox v-model:checked="copyForm.teachers">教师</n-checkbox>
          <n-checkbox v-model:checked="copyForm.rooms">场地</n-checkbox>
          <n-checkbox v-model:checked="copyForm.classes">班级</n-checkbox>
          <n-checkbox v-model:checked="copyForm.constraint_config" data-testid="copy-config">
            排课偏好设置
          </n-checkbox>
        </n-space>
        <n-space align="center">
          <n-switch v-model:value="copyForm.grade_promotion" />
          <n-text>班级年级自动进位(毕业年级不复制)</n-text>
        </n-space>
        <n-button
          type="primary" data-testid="copy-confirm"
          :disabled="!copyForm.start_date || !copyForm.end_date" @click="onCopy"
        >
          建立新学期
        </n-button>
      </n-space>
    </n-modal>
  </div>
</template>
