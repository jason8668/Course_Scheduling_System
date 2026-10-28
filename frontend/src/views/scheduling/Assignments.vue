<script setup lang="ts">
import {
  NAlert, NButton, NCard, NCheckbox, NDivider, NEmpty, NInputNumber, NModal, NPopconfirm,
  NRadioButton, NRadioGroup, NSelect, NSpace, NSwitch, NTag, NText, useMessage,
} from 'naive-ui'
import { classLabel } from '@/utils/labels'
import { computed, onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import {
  WEEK_LABELS, createAlternate, createAssignment, createGroup, deleteAssignment, deleteGroup,
  listAlternates, listAssignments, listGroups, updateAssignment, teacherLoad, classLoad,
} from '@/api/assignments'
import type {
  Assignment, AssignmentPayload, ClassLoad, SchedulingUnit, TeacherLoad, WeekParity,
} from '@/api/assignments'
import { listClassUnits, listRooms, listSubjects, listTeachers, ROOM_TYPE_LABELS } from '@/api/basedata'
import type { ClassUnit, Room, Subject, Teacher } from '@/api/basedata'
import { gradeLabel } from '@/api/substitutionLog'
import { listSemesters } from '@/api/semesters'
import type { SemesterListItem } from '@/api/semesters'

const message = useMessage()

const semesters = ref<SemesterListItem[]>([])
const sid = ref<number | null>(null)
const semesterOptions = computed(() => semesters.value.map((s) => ({ label: s.label, value: s.id })))

const classes = ref<ClassUnit[]>([])
const subjects = ref<Subject[]>([])
const teachers = ref<Teacher[]>([])
const rooms = ref<Room[]>([])
const groups = ref<SchedulingUnit[]>([])
const alternates = ref<SchedulingUnit[]>([])
const assignments = ref<Assignment[]>([])
const loads = ref<TeacherLoad[]>([])
const classLoads = ref<ClassLoad[]>([])

const classOptions = computed(() =>
  classes.value.map((c) => ({ label: classLabel(c), value: c.id })))

// 按年级筛选配课清单(一次只看一个年级);写操作仍由后端按帐号权限拦截
const gradeFilter = ref<number | null>(null)
const gradeFilterOptions = computed(() => {
  const grades = [...new Set(
    assignments.value.flatMap((a) => a.scheduling_unit.classes.map((c) => c.grade)),
  )].sort((a, b) => a - b)
  return grades.map((g) => ({ label: gradeLabel(g), value: g }))
})
const filteredAssignments = computed(() =>
  gradeFilter.value === null
    ? assignments.value
    : assignments.value.filter((a) =>
        a.scheduling_unit.classes.some((c) => c.grade === gradeFilter.value)),
)
const subjectOptions = computed(() => subjects.value.map((s) => ({ label: s.name, value: s.id })))
// 配课选老师默认只列本年级:目标班级/群组的年级 + 未填所属年级的老师
// (未填不隐藏,避免旧数据补填之前选不到人);已选的老师始终保留,避免编辑旧配课时选中项消失
const onlySameGrade = ref(true)
const formGrades = computed<number[]>(() => {
  if (form.value.target === 'single') {
    const g = classes.value.find((c) => c.id === form.value.class_id)?.grade
    return g == null ? [] : [g]
  }
  const unit = [...groups.value, ...alternates.value]
    .find((u) => u.id === form.value.scheduling_unit_id)
  return [...new Set((unit?.classes ?? []).map((c) => c.grade))]
})
const teacherOptions = computed(() => teachers.value
  .filter((t) => {
    if (!onlySameGrade.value || formGrades.value.length === 0) return true
    if (form.value.teacher_ids.includes(t.id)) return true
    const grades = t.grade_ids ?? []
    return grades.length === 0 || grades.some((g) => formGrades.value.includes(g))
  })
  .map((t) => ({ label: t.name, value: t.id })))
const roomOptions = computed(() => rooms.value.map((r) => ({ label: r.name, value: r.id })))
const roomTypeOptions = Object.entries(ROOM_TYPE_LABELS).map(([value, label]) => ({ label, value }))
const groupOptions = computed(() => groups.value.map((g) => ({ label: g.name, value: g.id })))
const alternateOptions = computed(() =>
  alternates.value.map((g) => ({ label: g.name, value: g.id })))
/** 单双周组已经配了哪几周(引导组长补齐另一笔) */
function weeksOf(u: SchedulingUnit): { odd?: Assignment; even?: Assignment } {
  const out: { odd?: Assignment; even?: Assignment } = {}
  for (const a of assignments.value) {
    if (a.scheduling_unit.id === u.id && a.week_parity) out[a.week_parity] = a
  }
  return out
}

async function loadBase(id: number) {
  ;[classes.value, subjects.value, teachers.value, rooms.value] = await Promise.all([
    listClassUnits(id), listSubjects(id), listTeachers(id), listRooms(id),
  ])
}
async function reloadAll(id: number) {
  ;[assignments.value, groups.value, alternates.value, loads.value, classLoads.value] =
    await Promise.all([
      listAssignments(id), listGroups(id), listAlternates(id), teacherLoad(id), classLoad(id),
    ])
}
async function onSemesterChange(id: number) {
  sid.value = id
  await loadBase(id)
  await reloadAll(id)
}

onMounted(async () => {
  semesters.value = await listSemesters()
  if (semesters.value.length) await onSemesterChange(semesters.value[0].id)
})

const overCapacity = computed(() => classLoads.value.filter((c) => c.over_capacity))
// 超课时本身是合法的(超出的节数另计课时费),只有超过上限才是问题。
// 旧版把任何 delta>0 都标红,会让正常配课看起来像出错。
function loadTagType(l: TeacherLoad): 'success' | 'error' | 'warning' | 'info' {
  if (l.over_limit) return 'error'
  if (l.delta > 0) return 'warning'
  if (l.delta < 0) return 'info'
  return 'success'
}

// 单双周的课课时算一半,可能出现 .5
function num(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(1)
}

function loadTagText(l: TeacherLoad): string {
  if (l.delta > 0) {
    return l.over_limit
      ? `+${num(l.delta)} 超过上限 ${l.max_overtime}`
      : `+${num(l.delta)} 超课时`
  }
  return l.delta < 0 ? `${num(l.delta)} 不足` : '刚好'
}

// ── 配课 modal ──
const show = ref(false)
const editingId = ref<number | null>(null)
interface AForm {
  target: 'single' | 'group' | 'alternate'
  class_id: number | null
  scheduling_unit_id: number | null
  subject_id: number | null
  teacher_ids: number[]
  lead_teacher_id: number | null
  periods_per_week: number
  block_rules: { block_size: number; count_per_week: number }[]
  required_room_type: string | null
  room_id: number | null
  lock_room: boolean
  week_parity: WeekParity | null
}
function emptyForm(): AForm {
  return {
    target: 'single', class_id: null, scheduling_unit_id: null, subject_id: null,
    teacher_ids: [], lead_teacher_id: null, periods_per_week: 1, block_rules: [],
    required_room_type: null, room_id: null, lock_room: false, week_parity: null,
  }
}
const form = ref<AForm>(emptyForm())
const leadOptions = computed(() =>
  teachers.value.filter((t) => form.value.teacher_ids.includes(t.id))
    .map((t) => ({ label: t.name, value: t.id })))

function openCreate() {
  editingId.value = null
  form.value = emptyForm()
  show.value = true
}
/** 从单双周组卡片直接新增那一组缺的那一周 */
function openCreateWeek(u: SchedulingUnit, week: WeekParity, from?: Assignment) {
  editingId.value = null
  form.value = {
    ...emptyForm(), target: 'alternate', scheduling_unit_id: u.id, week_parity: week,
    // 另一周的节数与连堂要相同,先带入
    periods_per_week: from?.periods_per_week ?? 1,
    block_rules: from?.block_rules.map((b) => ({ ...b })) ?? [],
  }
  show.value = true
}
function openEdit(a: Assignment) {
  editingId.value = a.id
  const kind = a.scheduling_unit.unit_type
  const isGroup = kind !== 'single'
  form.value = {
    target: kind === 'alternate' ? 'alternate' : isGroup ? 'group' : 'single',
    week_parity: a.week_parity,
    class_id: isGroup ? null : (a.scheduling_unit.classes[0]?.id ?? null),
    scheduling_unit_id: isGroup ? a.scheduling_unit.id : null,
    subject_id: a.subject.id,
    teacher_ids: a.teachers.map((t) => t.teacher_id),
    lead_teacher_id: a.teachers.find((t) => t.is_lead)?.teacher_id ?? null,
    periods_per_week: a.periods_per_week,
    block_rules: a.block_rules.map((b) => ({ block_size: b.block_size, count_per_week: b.count_per_week })),
    required_room_type: a.required_room_type,
    room_id: a.room_id,
    lock_room: a.lock_room,
  }
  show.value = true
}
function addBlock() {
  form.value.block_rules.push({ block_size: 2, count_per_week: 1 })
}
function removeBlock(i: number) {
  form.value.block_rules.splice(i, 1)
}

async function save() {
  const f = form.value
  if (f.target === 'single' && !f.class_id) return message.warning('请选择班级')
  if (f.target === 'group' && !f.scheduling_unit_id) return message.warning('请选择跑班群组')
  if (f.target === 'alternate' && !f.scheduling_unit_id) return message.warning('请选择单双周组')
  if (f.target === 'alternate' && !f.week_parity) return message.warning('请选择单周或双周')
  if (!f.subject_id) return message.warning('请选择科目')
  if (f.teacher_ids.length === 0) return message.warning('请至少指定一位教师')
  const lead = f.lead_teacher_id && f.teacher_ids.includes(f.lead_teacher_id)
    ? f.lead_teacher_id : f.teacher_ids[0]
  const payload: AssignmentPayload = {
    class_id: f.target === 'single' ? f.class_id : null,
    scheduling_unit_id: f.target === 'single' ? null : f.scheduling_unit_id,
    week_parity: f.target === 'alternate' ? f.week_parity : null,
    subject_id: f.subject_id,
    periods_per_week: f.periods_per_week,
    teachers: f.teacher_ids.map((id) => ({ teacher_id: id, is_lead: id === lead })),
    block_rules: f.block_rules,
    required_room_type: (f.required_room_type as AssignmentPayload['required_room_type']) || null,
    room_id: f.room_id,
    lock_room: f.lock_room,
  }
  try {
    if (editingId.value) await updateAssignment(editingId.value, payload)
    else await createAssignment(sid.value!, payload)
    show.value = false
    message.success('已储存配课')
    await reloadAll(sid.value!)
  } catch (e) {
    message.error((e as ApiError).detail || '储存失败')
  }
}
async function removeAssignment(a: Assignment) {
  await deleteAssignment(a.id)
  message.success('已删除')
  await reloadAll(sid.value!)
}

// ── 跑班群组 modal ──
const groupShow = ref(false)
const groupForm = ref<{ name: string; class_ids: number[] }>({ name: '', class_ids: [] })
function openGroup() {
  groupForm.value = { name: '', class_ids: [] }
  groupShow.value = true
}
async function saveGroup() {
  if (!groupForm.value.name) return message.warning('请输入群组名称')
  if (groupForm.value.class_ids.length < 2) return message.warning('跑班群组至少需 2 个班级')
  try {
    await createGroup(sid.value!, groupForm.value)
    groupShow.value = false
    message.success('已建立跑班群组')
    await reloadAll(sid.value!)
  } catch (e) {
    message.error((e as ApiError).detail || '建立失败')
  }
}
async function removeGroup(g: SchedulingUnit) {
  try {
    await deleteGroup(g.id)
    message.success('已删除群组')
    await reloadAll(sid.value!)
  } catch (e) {
    message.error((e as ApiError).detail || '删除失败(群组可能仍有配课)')
  }
}

// ── 单双周组 modal ──
const altShow = ref(false)
const altClass = ref<number | null>(null)
function openAlternate() {
  altClass.value = null
  altShow.value = true
}
async function saveAlternate() {
  if (!altClass.value) return message.warning('请选择班级')
  try {
    const u = await createAlternate(sid.value!, { class_id: altClass.value })
    altShow.value = false
    message.success(`已建立「${u.name}」,接著新增单周与双周的课`)
    await reloadAll(sid.value!)
  } catch (e) {
    message.error((e as ApiError).detail || '建立失败')
  }
}

function unitLabel(a: Assignment): string {
  const u = a.scheduling_unit
  if (u.unit_type === 'group') return `${u.name}(跑班)`
  if (u.unit_type === 'alternate') {
    return `${u.name}(${a.week_parity ? WEEK_LABELS[a.week_parity] : '未设周别'})`
  }
  const c = u.classes[0]
  return c ? classLabel(c) : u.name
}
function blockLabel(a: Assignment): string {
  if (a.block_rules.length === 0) return '—'
  return a.block_rules.map((b) => `${b.block_size}连堂×${b.count_per_week}`).join('、')
}
</script>

<template>
  <n-space vertical size="large">
    <n-space align="center">
      <h1 style="margin: 0">配课管理</h1>
      <n-select
        :value="sid" :options="semesterOptions" placeholder="选择学期"
        style="width: 240px" @update:value="onSemesterChange"
      />
    </n-space>

    <n-alert v-if="!sid" type="info">请先建立学期并于基础资料建立班级、科目、教师。</n-alert>

    <div v-else class="layout">
      <!-- 主区:配课清单 -->
      <n-space vertical size="large" style="flex: 1; min-width: 0">
        <n-space>
          <n-button type="primary" data-testid="assignment-add" @click="openCreate">新增配课</n-button>
          <n-button data-testid="group-add" @click="openGroup">新增跑班群组</n-button>
          <n-button data-testid="alt-add" @click="openAlternate">新增单双周组</n-button>
          <n-select
            v-model:value="gradeFilter" :options="gradeFilterOptions" style="width: 160px"
            placeholder="全部年级" clearable data-testid="a-grade-filter"
          />
        </n-space>

        <n-card title="配课清单" size="small">
          <n-empty v-if="filteredAssignments.length === 0" description="尚无配课" />
          <table v-else class="data-table">
            <thead>
              <tr><th>排课单位</th><th>科目</th><th>教师</th><th>周节数</th><th>连堂</th><th>场地</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="a in filteredAssignments" :key="a.id">
                <td>{{ unitLabel(a) }}</td>
                <td>{{ a.subject.name }}</td>
                <td>
                  <n-space size="small">
                    <n-tag
                      v-for="t in a.teachers" :key="t.teacher_id" size="small"
                      :type="t.is_lead ? 'success' : 'default'"
                    >
                      {{ t.name }}{{ t.is_lead ? '(主教)' : '' }}
                    </n-tag>
                  </n-space>
                </td>
                <td>{{ a.periods_per_week }}</td>
                <td>{{ blockLabel(a) }}</td>
                <td>{{ a.required_room_type ? ROOM_TYPE_LABELS[a.required_room_type] : '—' }}</td>
                <td>
                  <n-space>
                    <n-button size="tiny" @click="openEdit(a)">编辑</n-button>
                    <n-popconfirm @positive-click="removeAssignment(a)">
                      <template #trigger><n-button size="tiny" type="error" ghost>删除</n-button></template>
                      确定删除此配课?
                    </n-popconfirm>
                  </n-space>
                </td>
              </tr>
            </tbody>
          </table>
        </n-card>

        <n-card v-if="alternates.length" title="单双周组" size="small" data-testid="alt-list">
          <n-text depth="3" style="display: block; margin-bottom: 8px">
            同一格单周、双周轮流上两门课(学期第一周为单周)。单周、双周各配一笔,节数与连堂要相同。
          </n-text>
          <n-space vertical size="small">
            <n-space
              v-for="u in alternates" :key="u.id" align="center" justify="space-between"
              :data-testid="`alt-${u.name}`"
            >
              <n-space align="center" size="small">
                <strong>{{ u.name }}</strong>
                <template v-for="w in (['odd', 'even'] as const)" :key="w">
                  <n-tag v-if="weeksOf(u)[w]" size="small" type="success">
                    {{ WEEK_LABELS[w] }}:{{ weeksOf(u)[w]!.subject.name }}
                    {{ weeksOf(u)[w]!.teachers.map((t) => t.name).join('、') }}
                  </n-tag>
                  <n-button
                    v-else size="tiny" type="warning" dashed :data-testid="`alt-add-${w}`"
                    @click="openCreateWeek(u, w, weeksOf(u)[w === 'odd' ? 'even' : 'odd'])"
                  >
                    + 新增{{ WEEK_LABELS[w] }}的课
                  </n-button>
                </template>
              </n-space>
              <n-popconfirm @positive-click="removeGroup(u)">
                <template #trigger><n-button size="tiny" type="error" ghost>删除</n-button></template>
                删除单双周组将一并移除其配课,确定?
              </n-popconfirm>
            </n-space>
          </n-space>
        </n-card>

        <n-card v-if="groups.length" title="跑班群组" size="small">
          <n-space vertical size="small">
            <n-space v-for="g in groups" :key="g.id" align="center" justify="space-between">
              <n-text>
                <strong>{{ g.name }}</strong>
                <n-text depth="3" style="margin-left: 8px">
                  {{ g.classes.map((c) => classLabel(c)).join('、') }}
                </n-text>
              </n-text>
              <n-popconfirm @positive-click="removeGroup(g)">
                <template #trigger><n-button size="tiny" type="error" ghost>删除群组</n-button></template>
                删除群组将一并移除其配课,确定?
              </n-popconfirm>
            </n-space>
          </n-space>
        </n-card>
      </n-space>

      <!-- 侧栏:课时统计 -->
      <div class="sidebar">
        <n-card title="教师课时" size="small" data-testid="teacher-load">
          <n-empty v-if="loads.length === 0" description="尚无教师" size="small" />
          <table v-else class="data-table compact">
            <thead><tr><th>教师</th><th>已配/应授</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="l in loads" :key="l.teacher_id">
                <td>{{ l.name }}</td>
                <td>{{ num(l.assigned) }} / {{ l.target }}</td>
                <td>
                  <n-tag size="tiny" :type="loadTagType(l)">
                    {{ loadTagText(l) }}
                  </n-tag>
                </td>
              </tr>
            </tbody>
          </table>
        </n-card>

        <n-card title="班级节数警告" size="small" style="margin-top: 16px">
          <n-empty v-if="overCapacity.length === 0" description="各班配课未超出可排节次" size="small" />
          <n-space v-else vertical size="small" data-testid="class-warning">
            <n-alert v-for="c in overCapacity" :key="c.class_id" type="warning" :show-icon="false">
              {{ c.grade }}年{{ c.name }}:配课 {{ c.assigned }} 节 &gt; 可排 {{ c.capacity }} 节
            </n-alert>
          </n-space>
        </n-card>
      </div>
    </div>

    <!-- 配课 modal -->
    <n-modal v-model:show="show" preset="card" :title="editingId ? '编辑配课' : '新增配课'" style="max-width: 520px">
      <n-space vertical>
        <n-text>排课对象</n-text>
        <n-radio-group v-model:value="form.target">
          <n-radio-button value="single">单一班级</n-radio-button>
          <n-radio-button value="group">跑班群组</n-radio-button>
          <n-radio-button value="alternate" data-testid="a-target-alt">单双周组</n-radio-button>
        </n-radio-group>
        <n-select
          v-if="form.target === 'single'" v-model:value="form.class_id"
          data-testid="a-class" :options="classOptions" placeholder="选择班级" filterable
        />
        <n-select
          v-else-if="form.target === 'group'" v-model:value="form.scheduling_unit_id"
          :options="groupOptions" placeholder="选择跑班群组(需先建立)"
        />
        <template v-else>
          <n-select
            v-model:value="form.scheduling_unit_id" data-testid="a-alt-unit"
            :options="alternateOptions" placeholder="选择单双周组(需先建立)"
          />
          <n-radio-group v-model:value="form.week_parity" data-testid="a-week">
            <n-radio-button value="odd">单周</n-radio-button>
            <n-radio-button value="even">双周</n-radio-button>
          </n-radio-group>
        </template>

        <n-text>科目</n-text>
        <n-select v-model:value="form.subject_id" data-testid="a-subject" :options="subjectOptions" filterable placeholder="选择科目" />

        <n-text>授课教师(可多位协同,第一位默认主教)</n-text>
        <n-select v-model:value="form.teacher_ids" data-testid="a-teachers" multiple :options="teacherOptions" filterable placeholder="选择教师" />
        <n-space v-if="formGrades.length > 0" align="center">
          <n-text depth="3">只看本年级教师</n-text>
          <n-switch v-model:value="onlySameGrade" size="small" />
          <n-text depth="3">关掉可看全部教师</n-text>
        </n-space>
        <n-select
          v-if="form.teacher_ids.length > 1" v-model:value="form.lead_teacher_id"
          :options="leadOptions" placeholder="指定主教教师"
        />

        <n-space>
          <n-space vertical style="flex: 1">
            <n-text>每周节数</n-text>
            <n-input-number v-model:value="form.periods_per_week" data-testid="a-periods" :min="1" :max="40" />
          </n-space>
        </n-space>

        <n-space align="center" justify="space-between">
          <n-text>连堂规则</n-text>
          <n-button size="tiny" dashed data-testid="a-add-block" @click="addBlock">+ 新增连堂</n-button>
        </n-space>
        <n-space v-for="(b, i) in form.block_rules" :key="i" align="center">
          <n-input-number
            v-model:value="b.block_size" :data-testid="`a-block-size-${i}`"
            :min="2" :max="4" style="width: 110px"
          />
          <n-text>连堂 ×</n-text>
          <n-input-number
            v-model:value="b.count_per_week" :data-testid="`a-block-count-${i}`"
            :min="1" style="width: 110px"
          />
          <n-text>次/周</n-text>
          <n-button size="tiny" type="error" ghost @click="removeBlock(i)">移除</n-button>
        </n-space>

        <n-divider style="margin: 4px 0" />
        <n-text>场地需求(选填)</n-text>
        <n-space>
          <n-select v-model:value="form.required_room_type" :options="roomTypeOptions" clearable placeholder="场地类型" style="flex: 1" />
          <n-select v-model:value="form.room_id" :options="roomOptions" clearable placeholder="指定场地" style="flex: 1" />
        </n-space>
        <n-checkbox v-model:checked="form.lock_room">锁定场地(排课不得更动)</n-checkbox>

        <n-button type="primary" data-testid="a-save" @click="save">储存</n-button>
      </n-space>
    </n-modal>

    <!-- 单双周组 modal -->
    <n-modal v-model:show="altShow" preset="card" title="新增单双周组" style="max-width: 460px">
      <n-space vertical>
        <n-text depth="3">
          同一格单周、双周轮流上两门课,例如周一三、四节单周生科、双周资科。
          一组放一个班;建好后再新增单周、双周各一笔配课。
        </n-text>
        <n-text>班级</n-text>
        <n-select
          v-model:value="altClass" data-testid="alt-class" :options="classOptions"
          filterable placeholder="选择班级"
        />
        <n-button type="primary" data-testid="alt-save" @click="saveAlternate">建立</n-button>
      </n-space>
    </n-modal>

    <!-- 跑班群组 modal -->
    <n-modal v-model:show="groupShow" preset="card" title="新增跑班群组" style="max-width: 460px">
      <n-space vertical>
        <n-text>群组名称</n-text>
        <n-select
          v-model:value="groupForm.name" data-testid="group-name" filterable tag
          :options="[{ label: '高二多元选修', value: '高二多元选修' }, { label: '综高学程', value: '综高学程' }]"
          placeholder="输入或选择群组名称"
        />
        <n-text>成员班级(至少 2 班,须使用同一节次表)</n-text>
        <n-select v-model:value="groupForm.class_ids" data-testid="group-classes" multiple :options="classOptions" filterable placeholder="选择班级" />
        <n-button type="primary" data-testid="group-save" @click="saveGroup">建立</n-button>
      </n-space>
    </n-modal>
  </n-space>
</template>

<style scoped>
.layout { display: flex; gap: 24px; align-items: flex-start; }
.sidebar { width: 320px; flex-shrink: 0; }
.data-table { border-collapse: collapse; width: 100%; }
.data-table th, .data-table td { border: 1px solid var(--n-border-color, #e0e0e0); padding: 6px 8px; text-align: left; }
.data-table th { background: rgba(128,128,128,0.08); font-weight: 600; }
.data-table.compact th, .data-table.compact td { padding: 4px 6px; font-size: 13px; }
@media (max-width: 900px) { .layout { flex-direction: column; } .sidebar { width: 100%; } }
</style>
