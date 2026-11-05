<script setup lang="ts">
import {
  NButton, NCollapse, NCollapseItem, NDatePicker, NEmpty,
  NSelect, NSpace, NSwitch, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import type { ApiError } from '@/api/client'
import { listSemesters } from '@/api/semesters'
import { listTeachers } from '@/api/basedata'
import type { Teacher } from '@/api/basedata'
import { listLeaves } from '@/api/leaves'
import type { AffectedPeriod, LeaveRequest } from '@/api/leaves'
import {
  assignSubstitution, assignSubstitutionBatch, clearSubstitution, getRecommendations,
  getSwapOptions, listSubstitutionTypes, openSlips,
} from '@/api/substitutions'
import type { BatchSkip, Candidate, Recommendation, SwapOption, SwapOptions, SwapPartner } from '@/api/substitutions'
import { getDailyBoard, getSubstitutionLog } from '@/api/substitutionLog'
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
const semesters = ref<{ id: number; label: string }[]>([])
const sid = ref<number | null>(null)
const teachers = ref<Teacher[]>([])
const subTypes = ref<Record<string, string>>({})

const now = new Date()
const dateTs = ref<number | null>(new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime())
const dateIso = computed(() => (dateTs.value == null ? '' : toISODate(dateTs.value)))

const leaves = ref<LeaveRequest[]>([])
const board = ref<DailyBoard | null>(null)
const logEntries = ref<LogEntry[]>([])
const loading = ref(false)

const semesterOptions = computed(() => semesters.value.map((s) => ({ label: s.label, value: s.id })))
const teacherOptions = computed(() => teachers.value
  .filter((t) => t.is_active).map((t) => ({ label: t.name, value: t.id })))
/** 其他处置(代课走推荐、调课走下方调课按钮,这里只列剩下的处置方式) */
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
  if (!sid.value || !dateIso.value) return
  // 纪录区已退化为当日摘要:只查所选日期当天的纪录,全量查询走独立纪录页。
  logEntries.value = await getSubstitutionLog(sid.value, {
    teacherId: null,
    dateFrom: dateIso.value,
    dateTo: dateIso.value,
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
  await Promise.all([reloadBoard(), reloadLog()])
}

onMounted(async () => {
  const [sems, types] = await Promise.all(
    [listSemesters(), listSubstitutionTypes()])
  semesters.value = sems
  subTypes.value = types
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
  resetSwap()
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

// ── 调课(对调):处理页的调课面板平移过来(R2)──
// 展开中节次的可对调清单。swapTeacherId 为空 = 只看也教这个班的老师。
const swapOpen = ref(false)
const swap = ref<SwapOptions | null>(null)
const loadingSwap = ref(false)
const swapTeacherId = ref<number | null>(null)
// 找几周:沿用处理页的默认值(常和隔三周调的学校,每次都要重选很烦)
const swapWeeks = ref(2)
const SWAP_WEEK_OPTIONS = [
  { label: '本周与下周', value: 2 },
  { label: '往后共 3 周', value: 3 },
  { label: '往后共 4 周', value: 4 },
]
// 一位老师两周内可换的节次常有二、三十个;先只列同班的,其他班收起来(展开过的老师记在这里)
const swapExpanded = ref<Set<number>>(new Set())

function resetSwap() {
  swapOpen.value = false
  swap.value = null
  swapTeacherId.value = null
  swapExpanded.value = new Set()
}

/** 这位老师目前要显示的节次:有同班的就先只列同班,其他班等展开 */
function visibleOptions(partner: SwapPartner): SwapOption[] {
  const same = partner.options.filter((o) => o.same_class)
  if (!same.length || swapExpanded.value.has(partner.teacher_id)) return partner.options
  return same
}

function hiddenCount(partner: SwapPartner): number {
  return partner.options.length - visibleOptions(partner).length
}

function expandPartner(partner: SwapPartner) {
  swapExpanded.value = new Set([...swapExpanded.value, partner.teacher_id])
}

function swapTeacherOptions(l: LeaveRequest) {
  return teachers.value
    .filter((t) => t.is_active && t.id !== l.teacher_id)
    .map((t) => ({ label: t.name, value: t.id }))
}

async function loadSwap(p: AffectedPeriod) {
  loadingSwap.value = true
  try {
    swap.value = await getSwapOptions(p.id, swapTeacherId.value, swapWeeks.value)
  } finally {
    loadingSwap.value = false
  }
}

async function toggleSwap(p: AffectedPeriod) {
  swapOpen.value = !swapOpen.value
  if (swapOpen.value && !swap.value) await loadSwap(p)
}

async function onSwapTeacherChange(p: AffectedPeriod, id: number | null) {
  swapTeacherId.value = id
  await loadSwap(p)
}

async function onSwapWeeksChange(p: AffectedPeriod, weeks: number) {
  swapWeeks.value = weeks
  await loadSwap(p)
}

async function assignSwap(
  l: LeaveRequest, p: AffectedPeriod, partner: SwapPartner, opt: SwapOption,
) {
  try {
    await assignSubstitution(p.id, {
      type: 'swap',
      handler_teacher_id: partner.teacher_id,
      swap_entry_id: opt.entry_id,
      swap_date: opt.date,
      swap_period_no: opt.period_no,
    })
    message.success(
      `已和 ${partner.teacher_name} 调课:${l.teacher_name} 于 ${withWeekday(opt.date)} `
      + `${opt.period_name}补 ${opt.class_names} ${opt.subject_name}`)
    openPeriodId.value = null
    resetSwap()
    await reloadAll()
  } catch (e) {
    message.error((e as ApiError).message || '调课失败')
  }
}

</script>

<template>
  <div class="ios-page">
    <h1 class="ios-title">
      调代课中心
    </h1>
    <div class="ios-subtitle">
      一天的事情集中在这里处理，不用来回换页面
    </div>

    <n-space align="center" :wrap="true" style="margin-top: 16px">
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
      <RouterLink :to="{ name: 'daily-board', query: { semester_id: sid, date: dateIso } }">
        <n-button data-testid="center-daily-board">
          今日看板 →
        </n-button>
      </RouterLink>
    </n-space>
    <n-space style="margin-top: 12px">
      <span class="ios-chip-warn ios-chip">待处理 {{ pendingTotal }} 节</span>
      <span class="ios-chip">{{ dateIso }} 已安排 {{ boardCount }} 节</span>
      <span class="ios-chip-green ios-chip">{{ dateIso }} 请假 {{ absentToday }} 人</span>
    </n-space>

    <section class="ios-section">
      <div class="ios-section-title">
        <span>一 · 今日看板</span>
      </div>
      <div class="ios-card">
        <div class="ios-card-body">
          <n-space align="center" :wrap="true">
            <n-text>今日已安排 {{ boardCount }} 节 · 请假 {{ absentToday }} 人 · 待处理 {{ pendingTotal }} 节</n-text>
            <RouterLink :to="{ name: 'daily-board', query: { semester_id: sid, date: dateIso } }">
              <n-button size="small" type="primary" data-testid="center-board-summary">
                今日看板 →
              </n-button>
            </RouterLink>
          </n-space>
        </div>
      </div>
    </section>

    <section class="ios-section" style="animation-delay: 60ms">
      <div class="ios-section-title">
        <span>二 · 待处理处置</span>
      </div>
      <n-empty v-if="!activeLeaves.length" description="没有待处理的假单" />
      <div v-else style="display: flex; flex-direction: column; gap: 12px">
        <div v-for="l in activeLeaves" :key="l.id" class="ios-card">
          <div class="ios-row">
            <div class="ios-row-main">
              <span class="ios-row-title">{{ l.teacher_name }} · {{ l.leave_type_label }}</span>
              <span class="ios-row-sub" style="margin-left: 8px">{{ l.start_date }} ~ {{ l.end_date }}</span>
              <span class="ios-chip-warn ios-chip" style="margin-left: 8px">待处理 {{ pendingOf(l).length }} 节</span>
            </div>
            <n-button size="small" text type="primary" @click="openBatch(l)">
              整批指派
            </n-button>
            <n-button
              v-if="substituteIds(l).length" size="small" text type="primary"
              @click="printSlips('substitute', substituteIds(l))"
            >
              印代课单
            </n-button>
            <n-button
              v-if="swapIds(l).length" size="small" text type="primary"
              @click="printSlips('swap', swapIds(l))"
            >
              印调课单
            </n-button>
          </div>
          <div v-if="batchLeaveId === l.id" style="padding: 10px 16px; border-top: 1px solid rgba(0,0,0,0.06)">
            <n-space align="center" :wrap="true">
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
              <n-button size="small" type="primary" round :loading="batchBusy" @click="runBatch(l)">
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
          </div>
          <template v-for="p in pendingOf(l)" :key="p.id">
            <div class="ios-row">
              <span class="ios-row-main" style="border-left: 3px solid #ff9500; padding-left: 8px; font-size: 15px">
                {{ p.date }} {{ p.period_name }} · {{ p.class_names }}《{{ p.subject_name }}》
              </span>
              <n-button size="small" text type="primary" @click="openPeriod(p)">
                {{ openPeriodId === p.id ? '收起' : '指派' }}
              </n-button>
            </div>
            <div v-if="openPeriodId === p.id" style="padding: 4px 16px 12px; border-top: 1px solid rgba(0,0,0,0.06)">
              <n-space align="center" :wrap="true">
                <n-text>计入课时</n-text>
                <n-switch v-model:value="countsHours" />
                <n-select
                  v-model:value="otherType" :options="otherTypeOptions" placeholder="其他处置(自习/停课…)"
                  style="width: 180px" clearable
                />
                <n-button
                  v-if="otherType" size="small" round @click="assign(p, otherType)"
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
              <n-space v-else vertical size="small" style="margin-top: 8px">
                <n-space
                  v-for="c in rec?.candidates ?? []" :key="c.teacher_id"
                  align="center" :wrap="true"
                >
                  <n-text strong>
                    {{ c.teacher_name }}
                  </n-text>
                  <span v-if="c.same_grade" class="ios-chip-green ios-chip">同年级</span>
                  <span v-if="c.same_subject" class="ios-chip">同科目</span>
                  <span v-if="c.at_school_that_day" class="ios-chip-gray ios-chip">当天在校</span>
                  <n-text depth="3" style="font-size: 12px">
                    本月已代 {{ c.sub_periods_this_month }} 节
                  </n-text>
                  <n-button size="small" text type="primary" @click="assign(p, 'substitute', c)">
                    指派代课
                  </n-button>
                </n-space>
              </n-space>
              <n-space align="center" style="margin-top: 8px">
                <n-text depth="3">或改采调课：</n-text>
                <n-button size="small" :type="swapOpen ? 'primary' : 'default'" @click="toggleSwap(p)">
                  调课
                </n-button>
              </n-space>
              <div v-if="swapOpen" class="swap">
                <n-text depth="3" class="swap-intro">
                  调课 = 请另一位老师来上这一节，{{ l.teacher_name }}再找一天补回对方的一节（不计代课课时）。
                  <template v-if="swap">
                    以下是 {{ shortDate(swap.date_from) }} 到 {{ shortDate(swap.date_to) }}
                    之间，双方都有空的节次，点一下就成立。
                  </template>
                </n-text>
                <n-space align="center" size="small" style="margin-bottom: 6px">
                  <n-select
                    :value="swapTeacherId" :options="swapTeacherOptions(l)" filterable clearable
                    size="small" style="width: 200px" placeholder="只看也教这班的老师"
                    @update:value="(v: number | null) => onSwapTeacherChange(p, v)"
                  />
                  <n-text depth="3">也可以指定其他老师</n-text>
                  <n-text depth="3" style="margin-left: 12px">范围</n-text>
                  <n-select
                    :value="swapWeeks" :options="SWAP_WEEK_OPTIONS" size="small"
                    style="width: 140px" @update:value="(v: number) => onSwapWeeksChange(p, v)"
                  />
                </n-space>
                <n-text v-if="loadingSwap" depth="3">寻找可对调的节次…</n-text>
                <template v-else-if="swap">
                  <n-text v-if="!swap.partners.length" depth="3" class="swap-note">
                    {{ swapTeacherId ? '这位老师目前无法对调（可能已停用）。' : '没有其他老师也教这个班，可以从上方指定一位老师看看。' }}
                  </n-text>
                  <div
                    v-for="partner in swap.partners" :key="partner.teacher_id"
                    class="swap-partner"
                  >
                    <n-space align="center" size="small">
                      <b>{{ partner.teacher_name }}</b>
                      <span v-if="partner.teaches_same_class" class="ios-chip-green ios-chip">也教这班</span>
                    </n-space>
                    <n-text v-if="partner.blocked_reason" depth="3" class="swap-note">
                      无法对调：{{ partner.blocked_reason }}
                    </n-text>
                    <n-text v-else-if="!partner.options.length" depth="3" class="swap-note">
                      这段期间找不到双方都有空的节次，可试着放宽周数
                    </n-text>
                    <n-space v-else size="small" class="swap-note">
                      <n-button
                        v-for="opt in visibleOptions(partner)"
                        :key="`${opt.entry_id}-${opt.date}-${opt.period_no}`"
                        size="small" :type="opt.same_class ? 'primary' : 'default'" ghost
                        @click="assignSwap(l, p, partner, opt)"
                      >
                        {{ shortDate(opt.date) }} {{ opt.period_name }} ·
                        {{ opt.class_names }} {{ opt.subject_name }}
                        <span v-if="opt.in_block" class="swap-block">（连堂之一）</span>
                      </n-button>
                      <n-button
                        v-if="hiddenCount(partner)" size="small" text type="primary"
                        @click="expandPartner(partner)"
                      >
                        显示其他班级的 {{ hiddenCount(partner) }} 个节次
                      </n-button>
                    </n-space>
                  </div>
                </template>
              </div>
            </div>
          </template>
          <n-collapse v-if="resolvedOf(l).length" style="padding: 0 16px 8px">
            <n-collapse-item :title="`已处置 ${resolvedOf(l).length} 节`" :name="l.id">
              <n-space vertical size="small">
                <n-space
                  v-for="p in resolvedOf(l)" :key="p.id" align="center" :wrap="true"
                >
                  <n-text depth="2" style="font-size: 13px">
                    {{ p.date }} {{ p.period_name }} · {{ p.class_names }}《{{ p.subject_name }}》
                    {{ dispositionText(l, p) }}
                  </n-text>
                  <n-button size="small" text @click="clear(p)">
                    撤销
                  </n-button>
                </n-space>
              </n-space>
            </n-collapse-item>
          </n-collapse>
        </div>
      </div>
    </section>

    <section class="ios-section" style="animation-delay: 120ms">
      <div class="ios-section-title">
        <span>三 · 请假登记</span>
      </div>
      <div class="ios-card">
        <div class="ios-card-body">
          <n-space align="center" :wrap="true">
            <n-text depth="3">请假登记、跟进与销假都在「调课管理」页；登记后受影响节次会出现在上方待处理里。</n-text>
            <RouterLink :to="{ name: 'leaves' }">
              <n-button size="small" type="primary" data-testid="center-leave-entry">
                去登记请假 →
              </n-button>
            </RouterLink>
          </n-space>
        </div>
      </div>
    </section>

    <section class="ios-section" style="animation-delay: 180ms">
      <div class="ios-section-title">
        <span>四 · 调代课纪录</span>
      </div>
      <div class="ios-card">
        <div class="ios-card-body">
          <n-space align="center" :wrap="true">
            <n-text>{{ dateIso }} 调代课纪录 {{ logEntries.length }} 条</n-text>
            <RouterLink :to="{ name: 'substitution-log' }">
              <n-button size="small" type="primary" data-testid="center-log-all">
                查看全部纪录 →
              </n-button>
            </RouterLink>
          </n-space>
          <n-text v-if="!logEntries.length" depth="3" style="display: block; margin-top: 8px">该日暂无调代课纪录。</n-text>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.swap { margin-top: 8px; padding-top: 8px; border-top: 1px dashed rgba(128, 128, 128, 0.35); }
.swap-intro { display: block; margin-bottom: 6px; }
.swap-partner { margin: 6px 0; }
.swap-note { display: block; margin: 4px 0 0 12px; }
.swap-block { margin-left: 4px; opacity: 0.7; }
</style>
