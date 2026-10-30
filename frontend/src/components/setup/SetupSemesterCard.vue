<script setup lang="ts">
import {
  NButton, NDatePicker, NInputNumber, NPopconfirm, NRadioButton, NRadioGroup,
  NSelect, NSpace, NSwitch, NText, useMessage,
} from 'naive-ui'
import { computed, ref } from 'vue'
import type { ApiError } from '@/api/client'
import {
  copySemester, createSemester, deleteSemester, listTemplates,
} from '@/api/semesters'
import type { CopyOptions, SemesterListItem, Template } from '@/api/semesters'
import HelpTip from '@/components/HelpTip.vue'

const props = defineProps<{
  semesters: SemesterListItem[]
  semesterId: number | null
}>()
const emit = defineEmits<{
  select: [id: number]
  created: [id: number]
  deleted: []
}>()
const message = useMessage()

const semesterOptions = computed(() =>
  props.semesters.map((s) => ({ label: s.label, value: s.id })))

// ── 新建学期 ──
const year = ref(new Date().getFullYear())
const term = ref<1 | 2>(1)
const templateKey = ref<string | null>(null)
const templates = ref<Template[]>([])
const startTs = ref<number | null>(null)
const endTs = ref<number | null>(null)
const templateOptions = computed(() =>
  templates.value.map((t) => ({ label: t.name, value: t.key })))
async function loadTemplates() {
  try {
    templates.value = await listTemplates()
  } catch {
    templates.value = []
  }
}
void loadTemplates()
function fmtDate(ts: number | null): string | null {
  if (!ts) return null
  const d = new Date(ts)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}
async function onCreate() {
  try {
    const s = await createSemester({
      academic_year: year.value, term: term.value, template_key: templateKey.value,
      start_date: fmtDate(startTs.value), end_date: fmtDate(endTs.value),
    })
    message.success(`已建立${s.label}`)
    emit('created', s.id)
  } catch (e) {
    message.error((e as ApiError).detail || '建立学期失败')
  }
}

// ── 复制学期(新学期从旧学期带资料;升年级开关默认关,开则 7→8、8→9、9→7)──
const copyFrom = ref<number | null>(null)
const copyYear = ref(new Date().getFullYear())
const copyTerm = ref<1 | 2>(2)
const copyStartTs = ref<number | null>(null)
const copyEndTs = ref<number | null>(null)
const copyOpts = ref<Omit<CopyOptions, 'academic_year' | 'term' | 'start_date' | 'end_date'>>({
  period_tables: true, subjects: true, teachers: true, rooms: true, classes: true,
  grade_promotion: false, constraint_config: true,
})
async function onCopy() {
  if (!copyFrom.value) return message.warning('请选择要复制的学期')
  try {
    const s = await copySemester(copyFrom.value, {
      academic_year: copyYear.value, term: copyTerm.value,
      start_date: fmtDate(copyStartTs.value), end_date: fmtDate(copyEndTs.value),
      ...copyOpts.value,
    })
    message.success(`已复制为${s.label}`)
    emit('created', s.id)
  } catch (e) {
    message.error((e as ApiError).detail || '复制学期失败')
  }
}

async function onDelete() {
  if (!props.semesterId) return
  await deleteSemester(props.semesterId)
  message.success('已删除学期（其全部资料一并清除）')
  emit('deleted')
}
</script>

<template>
  <div>
    <n-space align="center" :wrap="true" style="margin-bottom: 12px">
      <n-text>当前学期</n-text>
      <n-select
        :value="semesterId" :options="semesterOptions" placeholder="选择学期"
        style="width: 220px" @update:value="(v: number) => emit('select', v)"
      />
      <n-popconfirm v-if="semesterId" @positive-click="onDelete">
        <template #trigger>
          <n-button size="small" text type="error">
            删除当前学期
          </n-button>
        </template>
        确定删除？该学期全部资料（基础资料、配课、课表）将一并清除。
      </n-popconfirm>
    </n-space>
    <n-space vertical size="small">
      <n-text strong style="font-size: 14px">
        新建学期
      </n-text>
      <n-space align="center" :wrap="true">
        <n-input-number v-model:value="year" :min="2000" :max="2100" style="width: 120px" />
        <n-text>学年</n-text>
        <n-radio-group v-model:value="term">
          <n-radio-button :value="1">
            第 1 学期
          </n-radio-button>
          <n-radio-button :value="2">
            第 2 学期
          </n-radio-button>
        </n-radio-group>
        <n-select
          v-model:value="templateKey" :options="templateOptions" placeholder="学制范本（可空）"
          style="width: 180px" clearable
        />
        <n-date-picker v-model:value="startTs" type="date" placeholder="开始日期" style="width: 150px" />
        <n-date-picker v-model:value="endTs" type="date" placeholder="结束日期" style="width: 150px" />
        <n-button size="small" type="primary" round @click="onCreate">
          建立学期
        </n-button>
      </n-space>
      <n-text strong style="font-size: 14px">
        复制旧学期开新学期
      </n-text>
      <n-space align="center" :wrap="true">
        <n-select
          v-model:value="copyFrom" :options="semesterOptions" placeholder="从哪个学期复制"
          style="width: 200px"
        />
        <n-input-number v-model:value="copyYear" :min="2000" :max="2100" style="width: 120px" />
        <n-radio-group v-model:value="copyTerm">
          <n-radio-button :value="1">
            第 1 学期
          </n-radio-button>
          <n-radio-button :value="2">
            第 2 学期
          </n-radio-button>
        </n-radio-group>
        <n-date-picker v-model:value="copyStartTs" type="date" placeholder="开始日期" style="width: 150px" />
        <n-date-picker v-model:value="copyEndTs" type="date" placeholder="结束日期" style="width: 150px" />
      </n-space>
      <n-space align="center" :wrap="true">
        <n-text>带节次表</n-text>
        <n-switch v-model:value="copyOpts.period_tables" size="small" />
        <n-text>带科目</n-text>
        <n-switch v-model:value="copyOpts.subjects" size="small" />
        <n-text>带教师</n-text>
        <n-switch v-model:value="copyOpts.teachers" size="small" />
        <n-text>带场地</n-text>
        <n-switch v-model:value="copyOpts.rooms" size="small" />
        <n-text>带班级</n-text>
        <n-switch v-model:value="copyOpts.classes" size="small" />
        <n-text>带软约束权重</n-text>
        <HelpTip testid="help-copy-constraint">软约束是排课时尽量满足的偏好，例如教师偏好时段、同科目分散在不同日、主科优先排上午，权重越大越优先满足。勾上就把旧学期调过的权重一起复制过来，不勾则新学期用默认值。</HelpTip>
        <n-switch v-model:value="copyOpts.constraint_config" size="small" />
        <n-text>升一年级（7→8、8→9、9→7）</n-text>
        <HelpTip testid="help-copy-promotion">开新学期时老师跟着学生升一年级：七年级老师升到八年级、八年级升到九年级，九年级老师回到七年级带新生。年级主任的年级范围也跟着走。不勾则老师年级原样复制。</HelpTip>
        <n-switch v-model:value="copyOpts.grade_promotion" size="small" />
        <n-button size="small" round @click="onCopy">
          复制开新学期
        </n-button>
      </n-space>
    </n-space>
  </div>
</template>
