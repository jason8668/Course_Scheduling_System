<script setup lang="ts">
import {
  NAlert, NButton, NDatePicker, NEmpty, NInput, NPopconfirm, NSelect, NSpace, NTag, NText, useMessage,
} from 'naive-ui'
import { computed, ref, watch } from 'vue'
import type { ApiError } from '@/api/client'
import { listAssignments } from '@/api/assignments'
import type { Assignment } from '@/api/assignments'
import { listClassUnits, listTeachers } from '@/api/basedata'
import type { ClassUnit, Teacher } from '@/api/basedata'
import { getMyTeacher, getPublishedTimetable } from '@/api/timetables'
import {
  approveTeacherSwap, createTeacherSwap, listTeacherSwaps, rejectTeacherSwap,
} from '@/api/teacherSwaps'
import type { TeacherSwap } from '@/api/teacherSwaps'
import { listSemesters } from '@/api/semesters'

const props = defineProps<{ semesterId?: number | null; admin: boolean }>()
const message = useMessage()

const swaps = ref<TeacherSwap[]>([])
const teachers = ref<Teacher[]>([])
const classes = ref<ClassUnit[]>([])
const assignments = ref<Assignment[]>([])
const me = ref<{ id: number; name: string } | null>(null)
const loading = ref(false)
const semesters = ref<{ id: number; label: string }[]>([])
const selectedSemesterId = ref<number | null>(props.semesterId ?? null)
const effectiveSemesterId = computed(() => props.semesterId ?? selectedSemesterId.value)

// 发起表单:换课那节 + 可选补课那节
const swapDateTs = ref<number | null>(null)
const swapPeriod = ref<number | null>(null)
const swapClass = ref<number | null>(null)
const swapAssignment = ref<number | null>(null)
const swapOriginal = ref<number | null>(null)
const swapHandler = ref<number | null>(null)
const note = ref('')
const withMakeup = ref(false)
const makeupDateTs = ref<number | null>(null)
const makeupPeriod = ref<number | null>(null)
const makeupClass = ref<number | null>(null)
const makeupAssignment = ref<number | null>(null)

function localDate(ts: number) {
  const d = new Date(ts)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

async function load() {
  const sid = effectiveSemesterId.value
  if (sid === null || sid === undefined) {
    swaps.value = []
    return
  }
  loading.value = true
  try {
    // 调课列表本身是教师可用接口,失败才报错。
    // 表单下拉数据与列表分开:下拉失败只留空,不弹错、不拖垮列表。
    try {
      swaps.value = await listTeacherSwaps(sid)
    } catch (e) {
      message.error((e as ApiError).detail ?? '载入调课失败')
    }
    if (props.admin) {
      // 管理员/主任:仍用主任专用接口(他们有权限)。
      ;[teachers.value, classes.value, assignments.value] = await Promise.all([
        listTeachers(sid),
        listClassUnits(sid),
        listAssignments(sid),
      ]).catch(() => [[], [], []] as [Teacher[], ClassUnit[], Assignment[]])
    } else {
      // 教师:原来这里也调 listTeachers/listClassUnits/listAssignments,
      // 那三支都要主任权限,纯教师帐号一律 403,Promise.all 一挂就整块弹
      // 「载入调课失败」或「权限不足」——这就是仪表板刷新报错的根因。
      // 改用已发布课表(教师可用、注释写明「教师端只需这一支」):
      // 它自带全部班级、教师与条目(条目含 course_assignment_id、班级、教师),
      // 足够拼出调课表单的班级/配课/教师下拉,不用再碰主任接口。
      try {
        const pub = await getPublishedTimetable(sid)
        if (pub) {
          teachers.value = pub.teachers.map((t) => ({ id: t.id, name: t.name })) as Teacher[]
          classes.value = pub.classes.map((c) => ({ id: c.id, name: c.name })) as ClassUnit[]
          const byId = new Map<number, Assignment>()
          for (const e of pub.entries) {
            if (byId.has(e.course_assignment_id)) continue
            byId.set(e.course_assignment_id, {
              id: e.course_assignment_id,
              subject: { name: e.subject },
              teachers: e.teacher_ids.map((tid, i) => ({
                teacher_id: tid, name: e.teachers[i] ?? `#${tid}`,
              })),
              scheduling_unit: {
                classes: e.class_ids.map((cid, i) => ({ id: cid, name: e.classes[i] ?? `#${cid}` })),
              },
            } as unknown as Assignment)
          }
          assignments.value = [...byId.values()]
        }
      } catch {
        teachers.value = []
        classes.value = []
        assignments.value = []
      }
      me.value = await getMyTeacher(sid).catch(() => null)
    }
  } finally {
    loading.value = false
  }
}
watch(effectiveSemesterId, load, { immediate: true })
watch(() => props.semesterId, (v) => { selectedSemesterId.value = v ?? null })
if (props.semesterId === null || props.semesterId === undefined) {
  listSemesters().then((list) => {
    semesters.value = list
    if (list.length && selectedSemesterId.value === null) selectedSemesterId.value = list[0].id
  }).catch(() => {})
}

const teacherOptions = computed(() => teachers.value.map((t) => ({ label: t.name, value: t.id })))
const classOptions = computed(() => classes.value.map((c) => ({ label: c.name, value: c.id })))
function assignmentOptionsFor(classId: number | null) {
  return assignments.value
    .filter((a) => classId === null || a.scheduling_unit.classes.some((c) => c.id === classId))
    .map((a) => ({ label: `${a.subject.name}(${a.teachers.map((t) => t.name).join('、')})`, value: a.id }))
}
const swapAssignmentOptions = computed(() => assignmentOptionsFor(swapClass.value))
const makeupAssignmentOptions = computed(() => assignmentOptionsFor(makeupClass.value))
function teacherName(id: number) {
  return teachers.value.find((t) => t.id === id)?.name ?? `#${id}`
}
function className(id: number) {
  return classes.value.find((c) => c.id === id)?.name ?? `#${id}`
}
function subjectName(assignmentId: number) {
  return assignments.value.find((a) => a.id === assignmentId)?.subject.name ?? ''
}
const statusLabel: Record<string, string> = { pending: '待对方确认', approved: '已生效', rejected: '已拒绝' }

async function onCreate() {
  const sid = effectiveSemesterId.value
  if (sid === null || sid === undefined || swapDateTs.value === null || !swapPeriod.value
    || !swapClass.value || !swapAssignment.value || !swapOriginal.value || !swapHandler.value) {
    message.warning('请把换课那节填完整(日期、节次、班级、配课、原任、换课)')
    return
  }
  if (withMakeup.value && (makeupDateTs.value === null || !makeupPeriod.value
    || !makeupClass.value || !makeupAssignment.value)) {
    message.warning('补课四项要填全(日期、节次、班级、配课)')
    return
  }
  try {
    await createTeacherSwap(sid, {
      class_date: localDate(swapDateTs.value),
      period_no: swapPeriod.value,
      class_unit_id: swapClass.value,
      course_assignment_id: swapAssignment.value,
      original_teacher_id: swapOriginal.value,
      handler_teacher_id: swapHandler.value,
      makeup_date: withMakeup.value && makeupDateTs.value ? localDate(makeupDateTs.value) : null,
      makeup_period_no: withMakeup.value ? makeupPeriod.value : null,
      makeup_class_unit_id: withMakeup.value ? makeupClass.value : null,
      makeup_assignment_id: withMakeup.value ? makeupAssignment.value : null,
      note: note.value.trim() || null,
    })
    message.success('已发起,对方确认后即生效')
    await load()
  } catch (e) {
    message.error((e as ApiError).detail ?? '发起失败')
  }
}
async function onDecide(row: TeacherSwap, approve: boolean) {
  try {
    await (approve ? approveTeacherSwap(row.id) : rejectTeacherSwap(row.id))
    message.success(approve ? '已确认,调课生效' : '已拒绝')
    await load()
  } catch (e) {
    message.error((e as ApiError).detail ?? '处理失败')
  }
}
</script>

<template>
  <section class="ios-section" data-testid="teacher-swap-section">
    <div class="ios-section-title">
      <span>老师调课</span>
      <span class="ios-row-sub">不走请假,对方确认即生效;事后补登也可以(日期填过去那天)</span>
    </div>
    <div class="ios-card">
      <div class="ios-card-body">
        <n-space v-if="semesterId === null || semesterId === undefined" align="center">
          <n-text>选择学期</n-text>
          <n-select
            v-model:value="selectedSemesterId" :options="semesters.map((s) => ({ label: s.label, value: s.id }))"
            placeholder="选择学期" style="width: 220px" data-testid="swap-semester"
          />
        </n-space>
        <n-alert v-if="effectiveSemesterId === null || effectiveSemesterId === undefined" type="info">
          请先选择学期。
        </n-alert>
        <template v-else-if="!loading || swaps.length">
          <div v-if="!admin">
            <n-text strong>发起调课</n-text>
            <div class="ios-row-sub">
              换课那节:原任教师的课由换课教师上;补课可选,填了就是原任去上对方的课。
              事后补登:已经上过的课,日期填过去那天,对方点确认即补记录。
            </div>
            <n-space vertical size="small" style="margin-top: 8px">
              <n-space align="center" :wrap="true">
                <n-date-picker v-model:value="swapDateTs" type="date" placeholder="日期" style="width: 160px" data-testid="swap-date" />
                <n-select v-model:value="swapPeriod" :options="Array.from({ length: 12 }, (_, i) => ({ label: `第${i + 1}节`, value: i + 1 }))" placeholder="节次" style="width: 110px" data-testid="swap-period" />
                <n-select v-model:value="swapClass" :options="classOptions" placeholder="班级" style="width: 140px" data-testid="swap-class" />
                <n-select v-model:value="swapAssignment" :options="swapAssignmentOptions" placeholder="配课(科目)" style="width: 220px" data-testid="swap-assignment" />
              </n-space>
              <n-space align="center" :wrap="true">
                <n-select v-model:value="swapOriginal" :options="teacherOptions" placeholder="原任教师" style="width: 160px" data-testid="swap-original" />
                <n-select v-model:value="swapHandler" :options="teacherOptions" placeholder="换课教师" style="width: 160px" data-testid="swap-handler" />
                <n-input v-model:value="note" placeholder="备注(可选,如口头已通知)" style="width: 220px" data-testid="swap-note" />
              </n-space>
              <n-space align="center" :wrap="true">
                <n-text>带补课</n-text>
                <input v-model="withMakeup" type="checkbox" data-testid="swap-with-makeup" />
                <template v-if="withMakeup">
                  <n-date-picker v-model:value="makeupDateTs" type="date" placeholder="补课日期" style="width: 160px" data-testid="swap-makeup-date" />
                  <n-select v-model:value="makeupPeriod" :options="Array.from({ length: 12 }, (_, i) => ({ label: `第${i + 1}节`, value: i + 1 }))" placeholder="补课节次" style="width: 110px" data-testid="swap-makeup-period" />
                  <n-select v-model:value="makeupClass" :options="classOptions" placeholder="补课班级" style="width: 140px" data-testid="swap-makeup-class" />
                  <n-select v-model:value="makeupAssignment" :options="makeupAssignmentOptions" placeholder="补课配课" style="width: 220px" data-testid="swap-makeup-assignment" />
                </template>
              </n-space>
              <n-button type="primary" round data-testid="swap-create" @click="onCreate">发起调课</n-button>
            </n-space>
          </div>
          <div style="margin-top: 16px">
            <n-text strong>{{ admin ? '全部调课记录(管理员只看,不批)' : '我的调课' }}</n-text>
            <n-empty v-if="!swaps.length" description="暂无调课记录" style="margin-top: 8px" />
            <div v-for="row in swaps" :key="row.id" class="ios-row" data-testid="swap-row">
              <div class="ios-row-main">
                <div class="ios-row-title">
                  {{ row.class_date }} 第{{ row.period_no }}节 {{ className(row.class_unit_id) }}
                  {{ subjectName(row.course_assignment_id) }}:
                  {{ teacherName(row.original_teacher_id) }} → {{ teacherName(row.handler_teacher_id) }}
                  <n-tag v-if="row.is_retroactive" size="small" type="info">事后补登</n-tag>
                </div>
                <div v-if="row.makeup_date" class="ios-row-sub">
                  补课: {{ row.makeup_date }} 第{{ row.makeup_period_no }}节
                  {{ row.makeup_class_unit_id ? className(row.makeup_class_unit_id) : '' }}
                  {{ row.makeup_assignment_id ? subjectName(row.makeup_assignment_id) : '' }}
                </div>
                <div v-if="row.note" class="ios-row-sub">{{ row.note }}</div>
              </div>
              <n-tag :type="row.status === 'approved' ? 'success' : row.status === 'rejected' ? 'error' : 'warning'">
                {{ statusLabel[row.status] }}
              </n-tag>
              <n-space v-if="!admin && me && row.status === 'pending' && row.approver_teacher_id === me.id">
                <n-button size="small" type="primary" :data-testid="`swap-approve-${row.id}`" @click="onDecide(row, true)">同意</n-button>
                <n-popconfirm @positive-click="onDecide(row, false)">
                  <template #trigger>
                    <n-button size="small" :data-testid="`swap-reject-${row.id}`">拒绝</n-button>
                  </template>
                  拒绝后这条调课不生效。
                </n-popconfirm>
              </n-space>
            </div>
          </div>
        </template>
      </div>
    </div>
  </section>
</template>
