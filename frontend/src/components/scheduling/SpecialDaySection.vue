/**
 * 特殊日课表(排课中心内的一节,不另设菜单)。
 * 一则规则 = 某范围(全校/某一年级)在某周期内,对若干班级×节次的课做替换;
 * 未填的节次沿用主课表,填了的替换(或取消)。发布后才生效。
 * 换课必须用教该班的配课:下拉只列其排课单位含该班的配课,拿别的班的配课来换会
 * 被后端 400 挡下(那是配课不教该班,不是换课)。
 */
<script setup lang="ts">
import {
  NAlert, NButton, NDatePicker, NEmpty, NInput, NInputNumber, NPopconfirm, NSelect,
  NSpace, NText, useMessage,
} from 'naive-ui'
import { computed, ref, watch } from 'vue'
import type { ApiError } from '@/api/client'
import { listClassUnits } from '@/api/basedata'
import type { ClassUnit } from '@/api/basedata'
import { listAssignments } from '@/api/assignments'
import type { Assignment } from '@/api/assignments'
import {
  SPECIAL_DAY_RECURRENCE_LABELS, WEEKDAY_LABELS,
  createSpecialDayRule, deleteSpecialDayRule, listSpecialDayRules,
  publishSpecialDayRule, replaceSpecialDayEntries, unpublishSpecialDayRule,
} from '@/api/specialDays'
import type { SpecialDayRule } from '@/api/specialDays'

const props = defineProps<{ semesterId: number | null }>()
const message = useMessage()

const rules = ref<SpecialDayRule[]>([])
const classes = ref<ClassUnit[]>([])
const assignments = ref<Assignment[]>([])

const form = ref({
  title: '',
  scopeType: 'school' as 'school' | 'grade',
  scopeId: null as number | null,
  recurrence: 'single' as 'single' | 'weekly' | 'monthly',
  singleTs: null as number | null,
  weekday: 1 as number | null,
  dayOfMonth: 1 as number | null,
  startTs: null as number | null,
  endTs: null as number | null,
})

function localDate(ts: number | null): string | null {
  if (ts === null) return null
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

const gradeOptions = computed(() => {
  const grades = [...new Set(classes.value.map((c) => c.grade))].sort((a, b) => a - b)
  return grades.map((g) => ({ label: `${g}年级`, value: g }))
})
const classOptions = computed(() => {
  let list = classes.value
  if (editing.value && editing.value.scope_type === 'grade' && editing.value.scope_id !== null) {
    list = list.filter((c) => c.grade === editing.value!.scope_id)
  }
  return list.map((c) => ({ label: c.name, value: c.id }))
})
const className = (id: number) => classes.value.find((c) => c.id === id)?.name ?? `班级${id}`
const assignmentLabel = (id: number | null) => {
  if (id === null || id === -1) return '取消这节'
  const a = assignments.value.find((x) => x.id === id)
  if (!a) return `配课${id}`
  return `${a.subject.name}(${a.teachers.map((t) => t.name).join('、')})`
}
const assignmentsForClass = (classId: number | null) => {
  // 下拉用 -1 代表取消(naive 的 select 选项不接受 null 值,保存时再转回 null)
  const opts = [{ label: '取消这节', value: -1 }]
  if (classId === null) return opts
  return opts.concat(assignments.value
    .filter((a) => a.scheduling_unit.classes.some((c) => c.id === classId))
    .map((a) => ({
      label: `${a.subject.name}(${a.teachers.map((t) => t.name).join('、')})`,
      value: a.id,
    })))
}
function recurrenceText(r: SpecialDayRule): string {
  const base = SPECIAL_DAY_RECURRENCE_LABELS[r.recurrence]
  if (r.recurrence === 'single') return `${base} ${r.single_date ?? ''}`
  if (r.recurrence === 'weekly') return `${base} ${WEEKDAY_LABELS[r.weekday ?? 0] ?? ''}`
  return `${base} ${r.day_of_month ?? ''}号`
}
function scopeText(r: SpecialDayRule): string {
  return r.scope_type === 'grade' ? `${r.scope_id}年级` : '全校'
}

async function load() {
  if (props.semesterId === null) {
    rules.value = []
    classes.value = []
    assignments.value = []
    return
  }
  const [rs, cs, as] = await Promise.all([
    listSpecialDayRules(props.semesterId),
    listClassUnits(props.semesterId),
    listAssignments(props.semesterId),
  ])
  rules.value = rs
  classes.value = cs
  assignments.value = as
}
watch(() => props.semesterId, load, { immediate: true })

const creating = ref(false)
async function onCreate() {
  if (props.semesterId === null) return
  if (!form.value.title.trim()) {
    message.warning('请先填规则名称,例如「运动会日」')
    return
  }
  creating.value = true
  try {
    await createSpecialDayRule(props.semesterId, {
      title: form.value.title.trim(),
      scope_type: form.value.scopeType,
      scope_id: form.value.scopeType === 'grade' ? form.value.scopeId : null,
      recurrence: form.value.recurrence,
      single_date: form.value.recurrence === 'single' ? localDate(form.value.singleTs) : null,
      weekday: form.value.recurrence === 'weekly' ? form.value.weekday : null,
      day_of_month: form.value.recurrence === 'monthly' ? form.value.dayOfMonth : null,
      start_date: localDate(form.value.startTs),
      end_date: localDate(form.value.endTs),
      entries: [],
    })
    message.success('规则已建立,接下来在下面编辑它的班级×节次,再点发布才生效')
    form.value.title = ''
    await load()
  } catch (e) {
    message.error((e as ApiError).detail ?? '建立失败')
  } finally {
    creating.value = false
  }
}

const editing = ref<SpecialDayRule | null>(null)
// 编辑行内部用 -1 代表取消,保存时转回 null(见 assignmentsForClass 注释)
const editRows = ref<{ class_unit_id: number; period_no: number; course_assignment_id: number }[]>([])
function openEdit(r: SpecialDayRule) {
  editing.value = r
  editRows.value = r.entries.map((e) => ({
    class_unit_id: e.class_unit_id,
    period_no: e.period_no,
    course_assignment_id: e.course_assignment_id ?? -1,
  }))
  if (!editRows.value.length) editRows.value.push({ class_unit_id: 0, period_no: 1, course_assignment_id: -1 })
}
function addRow() {
  editRows.value.push({ class_unit_id: 0, period_no: 1, course_assignment_id: -1 })
}
const saving = ref(false)
async function onSaveEntries() {
  if (!editing.value) return
  const rows = editRows.value.filter((r) => r.class_unit_id)
  const seen = new Set<string>()
  for (const r of rows) {
    const key = `${r.class_unit_id}-${r.period_no}`
    if (seen.has(key)) {
      message.warning('同一班级同一节次写了两次,请先去重')
      return
    }
    seen.add(key)
  }
  saving.value = true
  try {
    const updated = await replaceSpecialDayEntries(editing.value.id, rows.map((r) => ({
      ...r,
      course_assignment_id: r.course_assignment_id === -1 ? null : r.course_assignment_id,
    })))
    editing.value = updated
    message.success('已保存,点发布后才生效')
    await load()
    const fresh = rules.value.find((r) => r.id === updated.id)
    if (fresh) editing.value = fresh
  } catch (e) {
    message.error((e as ApiError).detail ?? '保存失败')
  } finally {
    saving.value = false
  }
}
async function onPublish(r: SpecialDayRule) {
  try {
    await publishSpecialDayRule(r.id)
    message.success('已发布:查课表、提醒、课时统计都会按这则规则换课')
    await load()
  } catch (e) {
    message.error((e as ApiError).detail ?? '发布失败')
  }
}
async function onUnpublish(r: SpecialDayRule) {
  try {
    await unpublishSpecialDayRule(r.id)
    message.success('已停用')
    await load()
  } catch (e) {
    message.error((e as ApiError).detail ?? '停用失败')
  }
}
async function onDelete(r: SpecialDayRule) {
  try {
    await deleteSpecialDayRule(r.id)
    if (editing.value?.id === r.id) editing.value = null
    message.success('已删除')
    await load()
  } catch (e) {
    message.error((e as ApiError).detail ?? '删除失败')
  }
}
</script>

<template>
  <section class="ios-section" style="animation-delay: 300ms">
    <div class="ios-section-title">
      <span>特殊日课表</span>
      <span class="ios-row-sub">某天或每周/每月固定日子换课:填了的节次换课,没填的沿用主课表</span>
    </div>
    <div class="ios-card">
      <div class="ios-card-body">
        <n-alert v-if="semesterId === null" type="info">
          请先在上方选择学期。
        </n-alert>
        <template v-else>
          <n-space vertical size="small">
            <n-space align="center" :wrap="true">
              <n-input v-model:value="form.title" placeholder="规则名称,例如运动会日" style="width: 200px" data-testid="sd-title" />
              <n-select
                v-model:value="form.scopeType"
                :options="[
                  { label: '全校', value: 'school' },
                  { label: '年级', value: 'grade' },
                ]" style="width: 100px" data-testid="sd-scope"
              />
              <n-select
                v-if="form.scopeType === 'grade'" v-model:value="form.scopeId"
                :options="gradeOptions" placeholder="选年级" style="width: 100px" data-testid="sd-grade"
              />
              <n-select
                v-model:value="form.recurrence"
                :options="[
                  { label: '单次某日', value: 'single' },
                  { label: '每周固定周几', value: 'weekly' },
                  { label: '每月固定几号', value: 'monthly' },
                ]" style="width: 140px" data-testid="sd-recurrence"
              />
              <n-date-picker v-if="form.recurrence === 'single'" v-model:value="form.singleTs" type="date" placeholder="哪一天" style="width: 150px" data-testid="sd-single" />
              <n-select
                v-if="form.recurrence === 'weekly'" v-model:value="form.weekday"
                :options="Object.entries(WEEKDAY_LABELS).map(([k, v]) => ({ label: v, value: Number(k) }))"
                style="width: 100px" data-testid="sd-weekday"
              />
              <n-input-number v-if="form.recurrence === 'monthly'" v-model:value="form.dayOfMonth" :min="1" :max="31" style="width: 100px" data-testid="sd-dom" />
              <n-text v-if="form.recurrence === 'monthly'" depth="3">号(缺那天的月份自动跳过)</n-text>
            </n-space>
            <n-space align="center" :wrap="true">
              <n-text depth="3">起止日不填 = 本学期</n-text>
              <n-date-picker v-model:value="form.startTs" type="date" placeholder="开始日(选填)" style="width: 150px" data-testid="sd-start" />
              <n-date-picker v-model:value="form.endTs" type="date" placeholder="结束日(选填)" style="width: 150px" data-testid="sd-end" />
              <n-button type="primary" round :loading="creating" data-testid="sd-create" @click="onCreate">
                新增规则
              </n-button>
            </n-space>
          </n-space>

          <n-empty v-if="!rules.length" description="尚无特殊日规则" style="padding: 24px 0" />
          <table v-else class="ios-table" style="margin-top: 12px">
            <thead>
              <tr><th>名称</th><th>范围</th><th>周期</th><th>条目</th><th>状态</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="r in rules" :key="r.id" data-testid="sd-rule">
                <td>{{ r.title }}</td>
                <td>{{ scopeText(r) }}</td>
                <td>{{ recurrenceText(r) }}</td>
                <td>{{ r.entries.length }} 条</td>
                <td>
                  <span :class="r.is_active ? 'ios-chip-green ios-chip' : 'ios-chip-gray ios-chip'">
                    {{ r.is_active ? '已发布' : '草稿' }}
                  </span>
                </td>
                <td>
                  <n-space>
                    <n-button size="small" text type="primary" data-testid="sd-edit" @click="openEdit(r)">
                      编辑条目
                    </n-button>
                    <n-button v-if="!r.is_active" size="small" text type="primary" data-testid="sd-publish" @click="onPublish(r)">
                      发布
                    </n-button>
                    <n-button v-else size="small" text data-testid="sd-unpublish" @click="onUnpublish(r)">
                      停用
                    </n-button>
                    <n-popconfirm @positive-click="onDelete(r)">
                      <template #trigger>
                        <n-button size="small" text type="error" data-testid="sd-delete">
                          删除
                        </n-button>
                      </template>
                      确定删除这则特殊日规则?其条目一并移除。
                    </n-popconfirm>
                  </n-space>
                </td>
              </tr>
            </tbody>
          </table>

          <div v-if="editing" style="margin-top: 16px" data-testid="sd-editor">
            <n-text strong>
              编辑「{{ editing.title }}」的班级×节次:每行 = 某个班的某节换成某门课,或取消这节
            </n-text>
            <div class="ios-row-sub">
              没列出的节次沿用主课表;整日重排就把该班那天的每节都列出来;放假那天特殊日不生效。
              同天同节多则规则冲突时,单次 &gt; 每周 &gt; 每月。
            </div>
            <n-space vertical size="small" style="margin-top: 8px">
              <n-space v-for="(row, i) in editRows" :key="i" align="center" :wrap="true">
                <n-select v-model:value="row.class_unit_id" :options="classOptions" placeholder="选班级" style="width: 160px" :data-testid="`sd-row-class-${i}`" />
                <n-text>第</n-text>
                <n-input-number v-model:value="row.period_no" :min="1" :max="12" style="width: 80px" :data-testid="`sd-row-period-${i}`" />
                <n-text>节换成</n-text>
                <n-select
                  v-model:value="row.course_assignment_id"
                  :options="assignmentsForClass(row.class_unit_id)"
                  placeholder="先选班级" style="width: 220px" :data-testid="`sd-row-assignment-${i}`"
                />
                <n-button size="small" text type="error" @click="editRows.splice(i, 1)">
                  删行
                </n-button>
              </n-space>
              <n-space>
                <n-button size="small" round @click="addRow">
                  加一行
                </n-button>
                <n-button type="primary" round :loading="saving" data-testid="sd-save" @click="onSaveEntries">
                  保存条目
                </n-button>
                <n-button size="small" text @click="editing = null">
                  收起
                </n-button>
              </n-space>
              <n-text depth="3">
                当前条目: {{ editing.entries.map((e) => `${className(e.class_unit_id)}第${e.period_no}节→${assignmentLabel(e.course_assignment_id)}`).join('、') || '无' }}
              </n-text>
            </n-space>
          </div>
        </template>
      </div>
    </div>
  </section>
</template>
