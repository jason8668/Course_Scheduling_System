<script setup lang="ts">
import {
  NButton, NEmpty, NInput, NInputNumber, NModal, NPopconfirm, NSelect, NSpace, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import {
  TRACK_LABELS, createClassUnit, deleteClassUnit, listClassUnits, listTeachers, updateClassUnit,
} from '@/api/basedata'
import type { ClassTrack, ClassUnit, Teacher } from '@/api/basedata'
import { getSemester } from '@/api/semesters'
import type { PeriodTable } from '@/api/semesters'

const props = defineProps<{ semesterId: number }>()
const message = useMessage()

const items = ref<ClassUnit[]>([])
const teachers = ref<Teacher[]>([])
const periodTables = ref<PeriodTable[]>([])
const search = ref('')

const trackOptions = (Object.keys(TRACK_LABELS) as ClassTrack[]).map((t) => ({
  label: TRACK_LABELS[t], value: t,
}))
const teacherOptions = computed(() => teachers.value.map((t) => ({ label: t.name, value: t.id })))
// 仅当该学期有 ≥2 套节次表时才需要让用户为班级指定(混合学制)
const showPeriodTable = computed(() => periodTables.value.length >= 2)
const periodTableOptions = computed(() =>
  periodTables.value.map((t) => ({ label: t.name + (t.is_default ? '(默认)' : ''), value: t.id })),
)
function tableName(id: number | null): string {
  if (id === null) return '默认'
  return periodTables.value.find((t) => t.id === id)?.name ?? '—'
}

async function reload() {
  items.value = await listClassUnits(props.semesterId, search.value || undefined)
}
onMounted(async () => {
  teachers.value = await listTeachers(props.semesterId)
  periodTables.value = (await getSemester(props.semesterId)).period_tables
  await reload()
})

const show = ref(false)
const editingId = ref<number | null>(null)
const form = ref<{
  grade: number; name: string; track: ClassTrack; department: string
  student_count: number | null; homeroom_teacher_id: number | null; period_table_id: number | null
}>({
  grade: 1, name: '', track: 'elementary', department: '',
  student_count: null, homeroom_teacher_id: null, period_table_id: null,
})

// 技高才显示群科栏位
const showDepartment = computed(() => form.value.track === 'vocational')

function openCreate() {
  editingId.value = null
  form.value = {
    grade: 1, name: '', track: 'elementary', department: '',
    student_count: null, homeroom_teacher_id: null, period_table_id: null,
  }
  show.value = true
}
function openEdit(c: ClassUnit) {
  editingId.value = c.id
  form.value = {
    grade: c.grade, name: c.name, track: c.track, department: c.department ?? '',
    student_count: c.student_count, homeroom_teacher_id: c.homeroom_teacher_id,
    period_table_id: c.period_table_id ?? null,
  }
  show.value = true
}

async function save() {
  if (!form.value.name) {
    message.warning('请输入班名')
    return
  }
  const body = {
    grade: form.value.grade,
    name: form.value.name,
    track: form.value.track,
    department: showDepartment.value ? form.value.department || null : null,
    student_count: form.value.student_count,
    homeroom_teacher_id: form.value.homeroom_teacher_id,
    period_table_id: showPeriodTable.value ? form.value.period_table_id : null,
  }
  try {
    if (editingId.value) await updateClassUnit(editingId.value, body)
    else await createClassUnit(props.semesterId, body)
    show.value = false
    message.success('已储存')
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '储存失败')
  }
}

async function remove(c: ClassUnit) {
  try {
    await deleteClassUnit(c.id)
    message.success('已删除')
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '删除失败')
  }
}
</script>

<template>
  <n-space vertical>
    <n-space>
      <n-input v-model:value="search" placeholder="搜寻班名" clearable style="width: 200px" @input="reload" />
      <n-button type="primary" round data-testid="class-add" @click="openCreate">新增班级</n-button>
    </n-space>

    <div class="ios-card">
      <n-empty v-if="items.length === 0" description="尚无班级" style="padding: 24px 0" />
      <template v-else>
        <div v-for="c in items" :key="c.id" class="ios-row">
          <div class="ios-row-main">
            <span class="ios-row-title">{{ c.name }}</span>
            <span class="ios-row-sub" style="margin-left: 8px">
              {{ c.grade }}年级 · {{ TRACK_LABELS[c.track] }}
              · {{ c.department || '无群科' }}
              · 班主任 {{ c.homeroom_teacher?.name || '—' }}
              <template v-if="showPeriodTable"> · 节次表 {{ tableName(c.period_table_id) }}</template>
              · {{ c.student_count ?? '—' }} 人
            </span>
          </div>
          <n-button size="small" text type="primary" @click="openEdit(c)">编辑</n-button>
          <n-popconfirm @positive-click="remove(c)">
            <template #trigger><n-button size="small" text type="error">删除</n-button></template>
            确定删除此班级?
          </n-popconfirm>
        </div>
      </template>
    </div>

    <n-modal v-model:show="show" preset="card" :title="editingId ? '编辑班级' : '新增班级'" style="max-width: 440px">
      <n-space vertical>
        <n-space>
          <n-space vertical>
            <n-text>年级</n-text>
            <n-input-number v-model:value="form.grade" :min="1" :max="12" style="width: 120px" />
          </n-space>
          <n-space vertical style="flex: 1">
            <n-text>班名</n-text>
            <n-input v-model:value="form.name" data-testid="class-name" placeholder="如:忠、甲、301" />
          </n-space>
        </n-space>
        <n-text>学制</n-text>
        <n-select v-model:value="form.track" :options="trackOptions" />
        <template v-if="showDepartment">
          <n-text>群科(技高)</n-text>
          <n-input v-model:value="form.department" placeholder="如:机械科" />
        </template>
        <n-text>班主任(选填)</n-text>
        <n-select
          v-model:value="form.homeroom_teacher_id"
          :options="teacherOptions"
          clearable
          placeholder="（未指定）"
        />
        <template v-if="showPeriodTable">
          <n-text>节次表</n-text>
          <n-select
            v-model:value="form.period_table_id"
            data-testid="class-period-table"
            :options="periodTableOptions"
            clearable
            placeholder="使用学期默认"
          />
        </template>
        <n-text>人数(选填)</n-text>
        <n-input-number v-model:value="form.student_count" :min="0" />
        <n-button type="primary" data-testid="class-save" @click="save">储存</n-button>
      </n-space>
    </n-modal>
  </n-space>
</template>
