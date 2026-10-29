<script setup lang="ts">
import {
  NButton, NCard, NCollapse, NCollapseItem, NDatePicker, NEmpty, NList, NListItem,
  NSelect, NSpace, NSwitch, NTag, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import type { ApiError } from '@/api/client'
import { listSemesters } from '@/api/semesters'
import { listTeachers } from '@/api/basedata'
import type { Teacher } from '@/api/basedata'
import { createLeave, listLeaves, listLeaveTypes } from '@/api/leaves'
import type { AffectedPeriod, LeaveRequest } from '@/api/leaves'
import {
  assignSubstitution, assignSubstitutionBatch, clearSubstitution, getRecommendations,
  listSubstitutionTypes, openSlips,
} from '@/api/substitutions'
import type { BatchSkip, Candidate, Recommendation } from '@/api/substitutions'
import { getDailyBoard, getSubstitutionLog, openPatrolSheets } from '@/api/substitutionLog'
import type { DailyBoard, LogEntry } from '@/api/substitutionLog'

const message = useMessage()
const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

function toISODate(ts: number): string {
  const d = new Date(ts)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
function withWeekday(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return `${iso}(${WEEKDAYS[new Date(y, m - 1, d).getDay()]})`
}
function shortDate(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return `${m}/${d}(${WEEKDAYS[new Date(y, m - 1, d).getDay()]})`
}
/** 所选日期所在周的周一~周日(纪录区默认看这一周) */
function weekRange(ts: number): [number, number] {
  const d = new Date(ts)
  const monday = new Date(d.getFullYear(), d.getMonth(), d.getDate() - ((d.getDay() + 6) % 7))
  return [monday.getTime(), monday.getTime() + 6 * 86400000]
}

const semesters = ref<{ id: number; label: string }[]>([])
const sid = ref<number | null>(null)
const teachers = ref<Teacher[]>([])
const subTypes = ref<Record<string, string>>({})
const leaveTypes = ref<Record<string, string>>({})

const now = new Date()
const dateTs = ref<number | null>(new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime())
const dateIso = computed(() => (dateTs.value == null ? '' : toISODate(dateTs.value)))

const leaves = ref<LeaveRequest[]>([])
const board = ref<DailyBoard | null>(null)
const logEntries = ref<LogEntry[]>([])
const logRange = ref<[number, number] | null>(dateTs.value == null ? null : weekRange(dateTs.value))
const logTeacher = ref<number | null>(null)
const loading = ref(false)

const semesterOptions = computed(() => semesters.value.map((s) => ({ label: s.label, value: s.id })))
const teacherOptions = computed(() => teachers.value
  .filter((t) => t.is_active).map((t) => ({ label: t.name, value: t.id })))
const leaveTypeOptions = computed(() =>
  Object.entries(leaveTypes.value).map(([value, label]) => ({ label, value })))
/** 其他处置(代课走推荐、调课走原页面,这里只列剩下的处置方式) */
const otherTypeOptions = computed(() => Object.entries(subTypes.value)
  .filter(([v]) => v !== 'substitute' && v !== 'swap')
  .map(([value, label]) => ({ label, value })))

const activeLeaves = computed(() =>
  leaves.value.filter((l) => l.status === 'registered' && l.affected_count > 0))
const pendingOf = (l: LeaveRequest): AffectedPeriod[] =>
  l.affected_periods.filter((p) => p.status === 'pending')
const resolvedOf = (l: LeaveRequest): AffectedPeriod[] =>
  l.affected_periods.filter((p) => p.status !== 'pending' && p.status !== 'cancelled')
const pendingTotal = computed(() =>
  activeLeaves.value.reduce((n, l) => n + pendingOf(l).length, 0))
const boardCount = computed(() => board.value?.entries.length ?? 0)
const absentToday = computed(() => new Set(
  (board.value?.entries ?? []).filter((e) => e.row_kind === 'leave').map((e) => e.absent_teacher_id),
).size)

async function reloadLeaves() {
  if (sid.value) leaves.value = await listLeaves(sid.value)
}
async function reloadBoard() {
  if (sid.value && dateIso.value) board.value = await getDailyBoard(sid.value, dateIso.value)
}
async function reloadLog() {
  if (!sid.value) return
  logEntries.value = await getSubstitutionLog(sid.value, {
    teacherId: logTeacher.value,
    dateFrom: logRange.value ? toISODate(logRange.value[0]) : null,
    dateTo: logRange.value ? toISODate(logRange.value[1]) : null,
  })
}
async function reloadAll() {
  loading.value = true
  try {
    await Promise.all([reloadLeaves(), reloadBoard(), reloadLog()])
  } finally {
    loading.value = false
  }
}

async function onSemesterChange(id: number) {
  sid.value = id
  teachers.value = await listTeachers(id)
  await reloadAll()
}
async function onDateChange() {
  if (dateTs.value != null) logRange.value = weekRange(dateTs.value)
  await Promise.all([reloadBoard(), reloadLog()])
}

onMounted(async () => {
  const [sems, types, ltypes] = await Promise.all(
    [listSemesters(), listSubstitutionTypes(), listLeaveTypes()])
  semesters.value = sems
  subTypes.value = types
  leaveTypes.value = ltypes
  if (semesters.value.length) await onSemesterChange(semesters.value[0].id)
})

// ── 单节指派 ──
const openPeriodId = ref<number | null>(null)
const rec = ref<Recommendation | null>(null)
const loadingRec = ref(false)
const countsHours = ref(true)
const otherType = ref<string | null>(null)
const fundingOf = (counts: boolean): string => counts ? '计入课时' : '不计入课时'

async function openPeriod(p: AffectedPeriod) {
  if (openPeriodId.value === p.id) {
    openPeriodId.value = null
    return
  }
  openPeriodId.value = p.id
  rec.value = null
  otherType.value = null
  countsHours.value = true
  loadingRec.value = true
  try {
    rec.value = await getRecommendations(p.id)
  } finally {
    loadingRec.value = false
  }
}

async function assign(p: AffectedPeriod, type: string, candidate?: Candidate) {
  try {
    await assignSubstitution(p.id, {
      type,
      handler_teacher_id: candidate?.teacher_id ?? null,
      counts_toward_hours: type === 'substitute' ? countsHours.value : null,
      funding_source: type === 'substitute' ? fundingOf(countsHours.value) : '',
    })
    message.success(candidate
      ? `已指派 ${candidate.teacher_name} ${subTypes.value[type]}`
      : `已设为${subTypes.value[type]}`)
    openPeriodId.value = null
    await reloadAll()
  } catch (e) {
    message.error((e as ApiError).message || '指派失败')
  }
}

async function clear(p: AffectedPeriod) {
  try {
    await clearSubstitution(p.id)
    message.success('已撤销处置')
    await reloadAll()
  } catch (e) {
    message.error((e as ApiError).message || '撤销失败')
  }
}

function dispositionText(l: LeaveRequest, p: AffectedPeriod): string {
  if (!p.sub_type) return p.handler_name ? `→ ${p.handler_name}` : ''
  const label = subTypes.value[p.sub_type] ?? p.sub_type
  const who = p.handler_name ? ` → ${p.handler_name}` : ''
  if (p.sub_type === 'swap' && p.swap_date) {
    return `${label}${who}(${l.teacher_name} ${shortDate(p.swap_date)} ${p.swap_period_name}补课)`
  }
  return `${label}${who}`
}

function swapIds(l: LeaveRequest): number[] {
  return l.affected_periods
    .filter((p) => p.sub_type === 'swap' && p.status !== 'cancelled')
    .map((p) => p.id)
}
function substituteIds(l: LeaveRequest): number[] {
  return l.affected_periods
    .filter((p) => (p.sub_type === 'substitute' || p.sub_type === 'merge')
      && p.status !== 'cancelled')
    .map((p) => p.id)
}
function printSlips(kind: 'swap' | 'substitute', ids: number[]) {
  if (sid.value) openSlips(kind, sid.value, ids)
}

// ── 整批指派 ──
const batchLeaveId = ref<number | null>(null)
const batchTeacher = ref<number | null>(null)
const batchCounts = ref(true)
const batchDate = ref('')
const batchBusy = ref(false)
const batchSkipped = ref<BatchSkip[]>([])
const batchDone = ref<number | null>(null)

function batchDateOptions(l: LeaveRequest) {
  const days = [...new Set(pendingOf(l).map((p) => p.date))].sort()
  return [
    { label: `整张假单(待处理 ${pendingOf(l).length} 节)`, value: '' },
    ...days.map((d) => ({
      label: `只派 ${withWeekday(d)}(${pendingOf(l).filter((p) => p.date === d).length} 节)`,
      value: d,
    })),
  ]
}
async function runBatch(l: LeaveRequest) {
  if (!batchTeacher.value) {
    message.warning('请先选代课老师')
    return
  }
  batchBusy.value = true
  try {
    const r = await assignSubstitutionBatch(l.id, {
      handler_teacher_id: batchTeacher.value,
      funding_source: fundingOf(batchCounts.value),
      counts_toward_hours: batchCounts.value,
      date: batchDate.value || null,
    })
    batchDone.value = r.assigned
    batchSkipped.value = r.skipped
    message.success(`已派 ${r.assigned} 节${r.skipped.length ? `，${r.skipped.length} 节派不成` : ''}`)
    await reloadAll()
  } catch (e) {
    message.error((e as ApiError).message || '整批指派失败')
  } finally {
    batchBusy.value = false
  }
}
function openBatch(l: LeaveRequest) {
  if (batchLeaveId.value === l.id) {
    batchLeaveId.value = null
    return
  }
  batchLeaveId.value = l.id
  batchTeacher.value = null
  batchCounts.value = true
  batchDate.value = ''
  batchSkipped.value = []
  batchDone.value = null
}

// ── 请假登记(管理员代登) ──
const lfTeacher = ref<number | null>(null)
const lfType = ref('')
const lfStart = ref<number | null>(null)
const lfEnd = ref<number | null>(null)
const lfReason = ref('')
const submittingLeave = ref(false)

async function submitLeave() {
  if (!sid.value) return
  if (!lfTeacher.value || !lfType.value || lfStart.value == null || lfEnd.value == null) {
    message.warning('请先选老师、假别与起讫日期')
    return
  }
  submittingLeave.value = true
  try {
    await createLeave(sid.value, {
      teacher_id: lfTeacher.value,
      leave_type: lfType.value,
      start_date: toISODate(lfStart.value),
      end_date: toISODate(lfEnd.value),
      reason: lfReason.value || undefined,
    })
    message.success('请假已登记')
    lfTeacher.value = null
    lfType.value = ''
    lfStart.value = null
    lfEnd.value = null
    lfReason.value = ''
    await reloadAll()
  } catch (e) {
    message.error((e as ApiError).message || '登记失败')
  } finally {
    submittingLeave.value = false
  }
}

// ── 看板与纪录打印 ──
function printDailyBoard() {
  if (sid.value && dateIso.value) {
    window.open(`/daily-board/print?semester_id=${sid.value}&date=${dateIso.value}`, '_blank')
  }
}
function printPatrol() {
  if (sid.value && dateIso.value) openPatrolSheets(sid.value, dateIso.value)
}
const logSwapIds = computed(() => logEntries.value
  .filter((e) => e.sub_type === 'swap' && e.status !== 'cancelled')
  .map((e) => e.affected_period_id))
const logSubstituteIds = computed(() => logEntries.value
  .filter((e) => (e.sub_type === 'substitute' || e.sub_type === 'merge') && e.status !== 'cancelled')
  .map((e) => e.affected_period_id))
</script>

<template>
  <n-space vertical size="medium" class="sub-center">
    <n-space align="center" :wrap="true">
      <h1 style="margin: 0">
        调代课中心
      </h1>
      <n-select
        v-model:value="sid" :options="semesterOptions" placeholder="学期"
        style="width: 220px" @update:value="onSemesterChange"
      />
      <n-date-picker
        v-model:value="dateTs" type="date" placeholder="日期"
        style="width: 160px" @update:value="onDateChange"
      />
      <n-button :loading="loading" @click="reloadAll">
        刷新
      </n-button>
    </n-space>
    <n-space>
      <n-tag type="warning" size="large">
        待处理 {{ pendingTotal }} 节
      </n-tag>
      <n-tag type="info" size="large">
        {{ dateIso }} 已安排 {{ boardCount }} 节
      </n-tag>
      <n-tag type="success" size="large">
        {{ dateIso }} 请假 {{ absentToday }} 人
      </n-tag>
    </n-space>

    <n-card title="待处理代课" :loading="loading">
      <template #header-extra>
        <RouterLink :to="{ name: 'substitutions' }">
          <n-button size="small" text type="primary">
            调课对调去原页面 →
          </n-button>
        </RouterLink>
      </template>
      <n-empty v-if="!activeLeaves.length" description="没有待处理的假单" />
      <n-list v-else>
        <n-list-item v-for="l in activeLeaves" :key="l.id">
          <n-space vertical size="small" style="width: 100%">
            <n-space align="center" :wrap="true">
              <n-text strong>
                {{ l.teacher_name }} · {{ l.leave_type_label }}
              </n-text>
              <n-text>{{ l.start_date }} ~ {{ l.end_date }}</n-text>
              <n-tag type="warning" size="small">
                待处理 {{ pendingOf(l).length }} 节
              </n-tag>
              <n-button size="small" type="primary" ghost @click="openBatch(l)">
                整批指派
              </n-button>
              <n-button
                v-if="substituteIds(l).length" size="small"
                @click="printSlips('substitute', substituteIds(l))"
              >
                印代课单
              </n-button>
              <n-button
                v-if="swapIds(l).length" size="small"
                @click="printSlips('swap', swapIds(l))"
              >
                印调课单
              </n-button>
            </n-space>
            <n-space v-if="batchLeaveId === l.id" align="center" :wrap="true">
              <n-select
                v-model:value="batchTeacher" :options="teacherOptions" placeholder="代课老师"
                style="width: 160px" filterable
              />
              <n-select
                v-model:value="batchDate" :options="batchDateOptions(l)"
                style="width: 220px"
              />
              <n-text>计入课时</n-text>
              <n-switch v-model:value="batchCounts" />
              <n-button size="small" type="primary" :loading="batchBusy" @click="runBatch(l)">
                一次派完
              </n-button>
              <n-text v-if="batchDone !== null" depth="3" style="font-size: 12px">
                已派 {{ batchDone }} 节
              </n-text>
              <n-text
                v-for="s in batchSkipped" :key="s.affected_period_id" depth="3" style="font-size: 12px"
              >
                {{ s.date }} {{ s.period_name }}派不成：{{ s.reason }}
              </n-text>
            </n-space>
            <n-space vertical size="small">
              <n-space
                v-for="p in pendingOf(l)" :key="p.id" vertical size="small"
                style="border-left: 3px solid #f0a020; padding-left: 8px"
              >
                <n-space align="center" :wrap="true">
                  <n-text>
                    {{ p.date }} {{ p.period_name }} · {{ p.class_names }}《{{ p.subject_name }}》
                  </n-text>
                  <n-button size="small" type="primary" @click="openPeriod(p)">
                    {{ openPeriodId === p.id ? '收起' : '指派' }}
                  </n-button>
                </n-space>
                <n-space v-if="openPeriodId === p.id" vertical size="small">
                  <n-space align="center" :wrap="true">
                    <n-text>计入课时</n-text>
                    <n-switch v-model:value="countsHours" />
                    <n-select
                      v-model:value="otherType" :options="otherTypeOptions" placeholder="其他处置(自习/停课…)"
                      style="width: 180px" clearable
                    />
                    <n-button
                      v-if="otherType" size="small" @click="assign(p, otherType)"
                    >
                      设为{{ subTypes[otherType] }}
                    </n-button>
                  </n-space>
                  <n-text v-if="loadingRec" depth="3">
                    正在找推荐人选…
                  </n-text>
                  <n-text v-else-if="rec && !rec.candidates.length" depth="3">
                    {{ rec.no_candidate_hint || '暂无推荐人选' }}
                  </n-text>
                  <n-space v-else vertical size="small">
                    <n-space
                      v-for="c in rec?.candidates ?? []" :key="c.teacher_id"
                      align="center" :wrap="true"
                    >
                      <n-text strong>
                        {{ c.teacher_name }}
                      </n-text>
                      <n-tag v-if="c.same_grade" size="small" type="success">
                        同年级
                      </n-tag>
                      <n-tag v-if="c.same_subject" size="small" type="info">
                        同科目
                      </n-tag>
                      <n-tag v-if="c.at_school_that_day" size="small">
                        当天在校
                      </n-tag>
                      <n-text depth="3" style="font-size: 12px">
                        本月已代 {{ c.sub_periods_this_month }} 节
                      </n-text>
                      <n-button size="small" type="primary" @click="assign(p, 'substitute', c)">
                        指派代课
                      </n-button>
                    </n-space>
                  </n-space>
                </n-space>
              </n-space>
            </n-space>
            <n-collapse v-if="resolvedOf(l).length">
              <n-collapse-item :title="`已处置 ${resolvedOf(l).length} 节`" :name="l.id">
                <n-space vertical size="small">
                  <n-space
                    v-for="p in resolvedOf(l)" :key="p.id" align="center" :wrap="true"
                  >
                    <n-text depth="2" style="font-size: 13px">
                      {{ p.date }} {{ p.period_name }} · {{ p.class_names }}《{{ p.subject_name }}》
                      {{ dispositionText(l, p) }}
                    </n-text>
                    <n-button size="small" @click="clear(p)">
                      撤销
                    </n-button>
                  </n-space>
                </n-space>
              </n-collapse-item>
            </n-collapse>
          </n-space>
        </n-list-item>
      </n-list>
    </n-card>

    <n-card :title="`${dateIso} 当日看板`" :loading="loading">
      <template #header-extra>
        <n-space>
          <n-button size="small" @click="printDailyBoard">
            打印今日板
          </n-button>
          <n-button size="small" @click="printPatrol">
            打印巡视表
          </n-button>
        </n-space>
      </template>
      <n-empty v-if="!board || !board.entries.length" description="当天没有调代课安排" />
      <table v-else style="width: 100%; border-collapse: collapse">
        <thead>
          <tr>
            <th style="text-align: left; padding: 4px 6px; border-bottom: 1px solid #eee">
              节次
            </th>
            <th style="text-align: left; padding: 4px 6px; border-bottom: 1px solid #eee">
              班级
            </th>
            <th style="text-align: left; padding: 4px 6px; border-bottom: 1px solid #eee">
              科目
            </th>
            <th style="text-align: left; padding: 4px 6px; border-bottom: 1px solid #eee">
              请假教师
            </th>
            <th style="text-align: left; padding: 4px 6px; border-bottom: 1px solid #eee">
              安排
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="e in board.entries" :key="e.affected_period_id + e.row_kind">
            <td style="padding: 4px 6px; border-bottom: 1px solid #f5f5f5">
              {{ e.period_name }}
            </td>
            <td style="padding: 4px 6px; border-bottom: 1px solid #f5f5f5">
              {{ e.class_names }}
            </td>
            <td style="padding: 4px 6px; border-bottom: 1px solid #f5f5f5">
              {{ e.subject_name }}
            </td>
            <td style="padding: 4px 6px; border-bottom: 1px solid #f5f5f5">
              {{ e.absent_teacher_name }}
            </td>
            <td style="padding: 4px 6px; border-bottom: 1px solid #f5f5f5">
              {{ e.handler_name ? `${e.sub_type_label ?? ''} → ${e.handler_name}` : e.status_label }}
            </td>
          </tr>
        </tbody>
      </table>
    </n-card>

    <n-card title="请假登记" :loading="loading">
      <n-space align="end" :wrap="true">
        <n-select
          v-model:value="lfTeacher" :options="teacherOptions" placeholder="请假老师"
          style="width: 160px" filterable
        />
        <n-select
          v-model:value="lfType" :options="leaveTypeOptions" placeholder="假别"
          style="width: 140px"
        />
        <n-date-picker v-model:value="lfStart" type="date" placeholder="开始日期" style="width: 160px" />
        <n-date-picker v-model:value="lfEnd" type="date" placeholder="结束日期" style="width: 160px" />
        <n-button type="primary" :loading="submittingLeave" @click="submitLeave">
          登记请假
        </n-button>
      </n-space>
      <n-text depth="3" style="font-size: 12px">
        管理员代登；老师自己请假仍在「请假登记」页。登记后受影响节次会出现在上方待处理里。
      </n-text>
    </n-card>

    <n-card title="调代课纪录" :loading="loading">
      <n-space align="center" :wrap="true">
        <n-date-picker
          v-model:value="logRange" type="daterange" placeholder="日期范围"
          style="width: 260px" @update:value="reloadLog"
        />
        <n-select
          v-model:value="logTeacher" :options="teacherOptions"
          placeholder="老师(清空=全部)" style="width: 160px" filterable clearable @update:value="reloadLog"
        />
        <n-button
          v-if="logSubstituteIds.length" size="small"
          @click="printSlips('substitute', logSubstituteIds)"
        >
          印代课单
        </n-button>
        <n-button
          v-if="logSwapIds.length" size="small"
          @click="printSlips('swap', logSwapIds)"
        >
          印调课单
        </n-button>
      </n-space>
      <n-empty v-if="!logEntries.length" description="该范围内没有纪录" style="margin-top: 12px" />
      <n-list v-else style="margin-top: 8px">
        <n-list-item v-for="e in logEntries" :key="e.affected_period_id + e.row_kind">
          <n-text style="font-size: 13px">
            {{ e.date }} {{ e.period_name }} · {{ e.class_names }}《{{ e.subject_name }}》
            · {{ e.absent_teacher_name }} {{ e.leave_type_label }}
            {{ e.handler_name ? `→ ${e.handler_name}(${e.sub_type_label ?? ''})` : `（${e.status_label}）` }}
          </n-text>
        </n-list-item>
      </n-list>
    </n-card>
  </n-space>
</template>

<style scoped>
/* 注意 Naive 的类名:内容区是 n-card-content(单横线),标题文字在 n-card-header__main 里
   (见 MyHome.vue 同款注释,写错类名等于没生效)。 */
.sub-center :deep(.n-card-header) {
  padding: 10px 16px 6px;
}
.sub-center :deep(.n-card-header__main) {
  font-size: 15px;
}
.sub-center :deep(.n-card-content) {
  padding: 12px 16px;
}
.sub-center :deep(.n-list-item) {
  padding-top: 8px;
  padding-bottom: 8px;
}
</style>
