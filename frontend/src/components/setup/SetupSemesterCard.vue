<script setup lang="ts">
import {
  NButton, NDatePicker, NInputNumber, NModal, NPopconfirm, NRadioButton, NRadioGroup,
  NSelect, NSpace, NSwitch, NText, useMessage,
} from 'naive-ui'
import { computed, ref } from 'vue'
import type { ApiError } from '@/api/client'
import {
  copySemester, createSemester, deleteSemester, listTemplates, updateSemester,
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
  updated: []
}>()
const message = useMessage()

// ── 编辑起讫日期(原单独“学期与节次表”页独有的功能,2026-11-04 起只放开学建置这里)──
// 请假只能登记在这个范围内,改动不影响已排好的课表。
const showEdit = ref(false)
const editForm = ref({ start_date: null as string | null, end_date: null as string | null })
function openEdit() {
  const sem = props.semesters.find((s) => s.id === props.semesterId)
  editForm.value = { start_date: sem?.start_date ?? null, end_date: sem?.end_date ?? null }
  showEdit.value = true
}
async function onSaveEdit() {
  if (!props.semesterId) return
  if (!editForm.value.start_date || !editForm.value.end_date) {
    message.warning('请填学期起讫日期')
    return
  }
  try {
    await updateSemester(props.semesterId, {
      start_date: editForm.value.start_date,
      end_date: editForm.value.end_date,
    })
    message.success('学期已更新')
    showEdit.value = false
    emit('updated')
  } catch (e) {
    message.error((e as ApiError).detail || '更新失败')
  }
}

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
  <div class="ss-compact">
    <div class="ss-block">
      <div class="ss-title">
        新建学期
      </div>
      <div class="ss-row">
        <n-input-number v-model:value="year" :min="2000" :max="2100" style="width: 96px" />
        <span class="ss-label">学年</span>
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
          style="width: 150px" clearable
        />
        <HelpTip testid="help-create-template">选了学制范本，新学期会直接带一套现成的节次表时段；不选则不带，节次表后面自己建。</HelpTip>
        <span class="ss-dates">
          <n-date-picker v-model:value="startTs" type="date" placeholder="开始日期" style="width: 132px" />
          <n-date-picker v-model:value="endTs" type="date" placeholder="结束日期" style="width: 132px" />
        </span>
        <n-button size="small" type="primary" round @click="onCreate">
          建立学期
        </n-button>
      </div>
    </div>

    <div class="ss-block">
      <div class="ss-title">
        复制旧学期开新学期
        <HelpTip testid="help-copy-intro">从旧学期把资料整个带到新学期，不用从零重建；下面开关选哪些要带，默认全带，升一年级默认关。</HelpTip>
      </div>
      <div class="ss-row">
        <n-select
          v-model:value="copyFrom" :options="semesterOptions" placeholder="从哪个学期复制"
          style="width: 180px"
        />
        <n-input-number v-model:value="copyYear" :min="2000" :max="2100" style="width: 96px" />
        <n-radio-group v-model:value="copyTerm">
          <n-radio-button :value="1">
            第 1 学期
          </n-radio-button>
          <n-radio-button :value="2">
            第 2 学期
          </n-radio-button>
        </n-radio-group>
        <span class="ss-dates">
          <n-date-picker v-model:value="copyStartTs" type="date" placeholder="开始日期" style="width: 132px" />
          <n-date-picker v-model:value="copyEndTs" type="date" placeholder="结束日期" style="width: 132px" />
        </span>
        <n-button size="small" round @click="onCopy">
          复制开新学期
        </n-button>
      </div>
      <div class="ss-row">
        <span class="ss-switch">
          <span class="ss-label">带节次表</span>
          <HelpTip testid="help-copy-period-tables">旧学期的节次表（每周几天、第几节几点到几点）一起复制过来，不用重排时段。</HelpTip>
          <n-switch v-model:value="copyOpts.period_tables" size="small" />
        </span>
        <span class="ss-switch">
          <span class="ss-label">带科目</span>
          <HelpTip testid="help-copy-subjects">旧学期的科目（语文、数学等）一起复制过来。</HelpTip>
          <n-switch v-model:value="copyOpts.subjects" size="small" />
        </span>
        <span class="ss-switch">
          <span class="ss-label">带教师</span>
          <HelpTip testid="help-copy-teachers">旧学期的教师档案（姓名、任教科目、所属年级）一起复制过来。</HelpTip>
          <n-switch v-model:value="copyOpts.teachers" size="small" />
        </span>
        <span class="ss-switch">
          <span class="ss-label">带场地</span>
          <HelpTip testid="help-copy-rooms">旧学期的教室和场地一起复制过来。</HelpTip>
          <n-switch v-model:value="copyOpts.rooms" size="small" />
        </span>
        <span class="ss-switch">
          <span class="ss-label">带班级</span>
          <HelpTip testid="help-copy-classes">旧学期的班级一起复制过来。</HelpTip>
          <n-switch v-model:value="copyOpts.classes" size="small" />
        </span>
        <span class="ss-switch">
          <span class="ss-label">带软约束权重</span>
          <HelpTip testid="help-copy-constraint">软约束是排课时尽量满足的偏好，例如教师偏好时段、同科目分散在不同日、主科优先排上午，权重越大越优先满足。勾上就把旧学期调过的权重一起复制过来，不勾则新学期用默认值。</HelpTip>
          <n-switch v-model:value="copyOpts.constraint_config" size="small" />
        </span>
        <span class="ss-switch">
          <span class="ss-label">升一年级（7→8、8→9、9→7）</span>
          <HelpTip testid="help-copy-promotion">开新学期时老师跟着学生升一年级：七年级老师升到八年级、八年级升到九年级，九年级老师回到七年级带新生。年级主任的年级范围也跟着走。不勾则老师年级原样复制。</HelpTip>
          <n-switch v-model:value="copyOpts.grade_promotion" size="small" />
        </span>
      </div>
    </div>

    <div class="ss-row ss-manage">
      <span class="ss-label">当前学期</span>
      <n-select
        :value="semesterId" :options="semesterOptions" placeholder="选择学期"
        style="width: 200px" @update:value="(v: number) => emit('select', v)"
      />
      <n-button v-if="semesterId" size="small" text type="primary" data-testid="setup-sem-edit" @click="openEdit">
        编辑起讫日期
      </n-button>
      <n-popconfirm v-if="semesterId" @positive-click="onDelete">
        <template #trigger>
          <n-button size="small" text type="error">
            删除当前学期
          </n-button>
        </template>
        确定删除？该学期全部资料（基础资料、配课、课表）将一并清除。
      </n-popconfirm>
    </div>

    <n-modal
      v-model:show="showEdit" preset="card" style="max-width: 420px"
      title="编辑学期起讫日期"
    >
      <n-space vertical size="small">
        <n-text>学期起讫日期</n-text>
        <n-space align="center">
          <n-date-picker
            v-model:formatted-value="editForm.start_date" value-format="yyyy-MM-dd"
            type="date" placeholder="开学日" style="width: 150px" data-testid="setup-sem-edit-start"
          />
          <n-text>~</n-text>
          <n-date-picker
            v-model:formatted-value="editForm.end_date" value-format="yyyy-MM-dd"
            type="date" placeholder="结业日" style="width: 150px" data-testid="setup-sem-edit-end"
          />
        </n-space>
        <n-text depth="3" style="font-size: 13px">
          请假只能登记在这个范围内;改动不影响已排好的课表。
        </n-text>
        <n-button type="primary" data-testid="setup-sem-edit-save" @click="onSaveEdit">储存</n-button>
      </n-space>
    </n-modal>
  </div>
</template>

<style scoped>
/* 紧缩排布(Jason 2026-11-04 定):整卡行距收紧,输入与按钮尽量排成一排,
   起讫日期绑成一对,换行时也不拆开;当前学期管理行沉底,与新建/复制分开。 */
.ss-compact {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.ss-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ss-title {
  font-size: 14px;
  font-weight: 600;
}
.ss-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.ss-dates {
  display: inline-flex;
  flex-wrap: nowrap;
  gap: 8px;
}
.ss-label {
  font-size: 13px;
}
.ss-switch {
  display: inline-flex;
  align-items: center;
  gap: 2px;
}
.ss-manage {
  padding-top: 10px;
  border-top: 1px solid rgba(0, 0, 0, 0.06);
}
</style>
