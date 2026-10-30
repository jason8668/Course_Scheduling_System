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

// 发起表单(教师模式,Jason 2026-10-30 定):老师只能调自己的课,不能帮别人调,
// 所以不再选配课/原任/别人的课——只选「日期、节次、我自己的那节课、对调老师」,
// 原任固定就是本人,后端本来就要求发起人是原任或换课其中一方且原任是该配课的任课教师。
// 我的课与对方的课都从已发布课表条目拼:一条条目可能带多个班,按班展开成一行。
interface SwapEntryChoice {
  key: string
  classId: number
  className: string
  assignmentId: number
  subject: string
}
const swapDateTs = ref<number | null>(null)
const swapPeriod = ref<number | null>(null)
const swapMyEntryKey = ref<string | null>(null)
const swapHandler = ref<number | null>(null)
const note = ref('')
const withMakeup = ref(false)
const makeupDateTs = ref<number | null>(null)
const makeupPeriod = ref<number | null>(null)
const makeupEntryKey = ref<string | null>(null)
interface TimetableEntryChoice extends SwapEntryChoice {
  weekday: number
  period: number
  teacherIds: number[]
}
const allEntries = ref<TimetableEntryChoice[]>([])

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
          // 按班展开的条目:一条目多班时,每个班一行,调课表单按班选课用
          allEntries.value = pub.entries.flatMap((e) => e.class_ids.map((cid, i) => ({
            key: `${e.course_assignment_id}-${cid}-${e.weekday}-${e.period_no}`,
            classId: cid,
            className: e.classes[i] ?? `#${cid}`,
            assignmentId: e.course_assignment_id,
            subject: e.subject,
            weekday: e.weekday,
            period: e.period_no,
            teacherIds: e.teacher_ids,
          })))
        }
      } catch {
        teachers.value = []
        classes.value = []
        assignments.value = []
        allEntries.value = []
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

// 对调老师:只能选别人,不能选自己
const counterpartOptions = computed(() => teachers.value
  .filter((t) => me.value === null || t.id !== me.value.id)
  .map((t) => ({ label: t.name, value: t.id })))
function weekdayOf(ts: number | null): number | null {
  if (ts === null) return null
  const d = new Date(ts).getDay()
  return d === 0 ? 7 : d
}
function entriesFor(teacherId: number | null, dateTs: number | null, period: number | null) {
  if (teacherId === null || dateTs === null || period === null) return []
  const wd = weekdayOf(dateTs)
  return allEntries.value
    .filter((e) => e.teacherIds.includes(teacherId) && e.weekday === wd && e.period === period)
    .map((e) => ({ label: `${e.className} ${e.subject}`, value: e.key }))
}
const swapMyEntryOptions = computed(() => entriesFor(me.value?.id ?? null, swapDateTs.value, swapPeriod.value))
const makeupEntryOptions = computed(() => entriesFor(swapHandler.value, makeupDateTs.value, makeupPeriod.value))
// 节次只列老师有课的节数(Jason 2026-10-30 定):先选日期,节次下拉只出那天(星期)
// 本人有课的节次;没课的节根本选不了,也就不会出现「选了第5节却无数据」。
// 补课同理:先选对调老师和补课日期,节次只出对方那天有课的节次。
function periodsFor(teacherId: number | null, dateTs: number | null) {
  if (teacherId === null || dateTs === null) return []
  const wd = weekdayOf(dateTs)
  const periods = [...new Set(
    allEntries.value
      .filter((e) => e.teacherIds.includes(teacherId) && e.weekday === wd)
      .map((e) => e.period),
  )].sort((a, b) => a - b)
  return periods.map((p) => ({ label: `第${p}节`, value: p }))
}
const swapPeriodOptions = computed(() => periodsFor(me.value?.id ?? null, swapDateTs.value))
const makeupPeriodOptions = computed(() => periodsFor(swapHandler.value, makeupDateTs.value))
// 换了上游就清掉下游已选的值,否则旧选择留在框里、选项又是空的,
// 框里会直接显示旧的 key(如 506-50-5-2),看起来像跳了别的数据。
watch(swapDateTs, () => { swapPeriod.value = null; swapMyEntryKey.value = null })
watch(swapPeriod, () => { swapMyEntryKey.value = null })
watch(makeupDateTs, () => { makeupPeriod.value = null; makeupEntryKey.value = null })
watch(makeupPeriod, () => { makeupEntryKey.value = null })
watch(swapHandler, () => { makeupEntryKey.value = null; makeupPeriod.value = null })
function findEntry(key: string | null) {
  return allEntries.value.find((e) => e.key === key) ?? null
}
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
  const myEntry = findEntry(swapMyEntryKey.value)
  if (sid === null || sid === undefined || swapDateTs.value === null || !swapPeriod.value
    || !myEntry || !me.value || !swapHandler.value) {
    message.warning('请把换课那节填完整(日期、节次、我自己的课、对调老师)')
    return
  }
  const makeupEntry = withMakeup.value ? findEntry(makeupEntryKey.value) : null
  if (withMakeup.value && (makeupDateTs.value === null || !makeupPeriod.value || !makeupEntry)) {
    message.warning('补课三项要填全(日期、节次、对方的课)')
    return
  }
  try {
    await createTeacherSwap(sid, {
      class_date: localDate(swapDateTs.value),
      period_no: swapPeriod.value,
      class_unit_id: myEntry.classId,
      course_assignment_id: myEntry.assignmentId,
      original_teacher_id: me.value.id,
      handler_teacher_id: swapHandler.value,
      makeup_date: withMakeup.value && makeupDateTs.value ? localDate(makeupDateTs.value) : null,
      makeup_period_no: withMakeup.value ? makeupPeriod.value : null,
      makeup_class_unit_id: withMakeup.value ? makeupEntry!.classId : null,
      makeup_assignment_id: withMakeup.value ? makeupEntry!.assignmentId : null,
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
              只能调自己的课:先选日期,节次只列你那天有课的节,没课的节选不了;
              再选那节的课(班级+科目),最后选对调老师就行,原任就是你本人,不用再选。
              补课可选,填了就是你去上对方那节课。事后补登:已经上过的课,日期填过去那天,
              对方点确认即补记录。
            </div>
            <n-alert v-if="me === null" type="warning" style="margin-top: 8px">
              你的账号尚未绑定教师档案,无法发起调课,请联系管理员开通。
            </n-alert>
            <n-space vertical size="small" style="margin-top: 8px">
              <n-space align="center" :wrap="true">
                <n-date-picker v-model:value="swapDateTs" type="date" placeholder="日期" style="width: 160px" data-testid="swap-date" />
                <n-select
                  v-model:value="swapPeriod" :options="swapPeriodOptions" :disabled="swapDateTs === null"
                  :placeholder="swapDateTs === null ? '先选日期' : (swapPeriodOptions.length ? '节次(只列你有课的节)' : '这天你没有课')"
                  style="width: 170px" data-testid="swap-period"
                />
                <n-select
                  v-model:value="swapMyEntryKey" :options="swapMyEntryOptions"
                  :placeholder="swapDateTs && swapPeriod ? '我的课' : '先选日期和节次,再选我的课'"
                  style="width: 220px" data-testid="swap-my-entry"
                />
                <n-select v-model:value="swapHandler" :options="counterpartOptions" placeholder="对调老师" style="width: 160px" data-testid="swap-handler" />
                <n-input v-model:value="note" placeholder="备注(可选,如口头已通知)" style="width: 220px" data-testid="swap-note" />
              </n-space>
              <n-space align="center" :wrap="true">
                <n-text>带补课</n-text>
                <input v-model="withMakeup" type="checkbox" data-testid="swap-with-makeup" />
                <template v-if="withMakeup">
                  <n-date-picker v-model:value="makeupDateTs" type="date" placeholder="补课日期" style="width: 160px" data-testid="swap-makeup-date" />
                  <n-select
                    v-model:value="makeupPeriod" :options="makeupPeriodOptions" :disabled="makeupDateTs === null || swapHandler === null"
                    :placeholder="makeupDateTs === null || swapHandler === null ? '先选对调老师和补课日期' : (makeupPeriodOptions.length ? '补课节次(只列对方有课的节)' : '对方这天没有课')"
                    style="width: 190px" data-testid="swap-makeup-period"
                  />
                  <n-select
                    v-model:value="makeupEntryKey" :options="makeupEntryOptions"
                    :placeholder="swapHandler ? '对方的课' : '先选对调老师,再选对方的课'"
                    style="width: 220px" data-testid="swap-makeup-entry"
                  />
                </template>
              </n-space>
              <n-button type="primary" round :disabled="me === null" data-testid="swap-create" @click="onCreate">发起调课</n-button>
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
