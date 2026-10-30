<script setup lang="ts">
import {
  NAlert, NButton, NEmpty, NModal, NSelect, NSpace, NSwitch, NTag, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import { listLeaves } from '@/api/leaves'
import type { AffectedPeriod, LeaveRequest } from '@/api/leaves'
import { listSemesters } from '@/api/semesters'
import { listTeachers } from '@/api/basedata'
import type { Teacher } from '@/api/basedata'
import {
  assignSubstitution, assignSubstitutionBatch, clearSubstitution, getRecommendations,
  getSwapOptions, listSubstitutionTypes, openSlips,
} from '@/api/substitutions'
import type {
  BatchSkip, Candidate, Recommendation, SwapOption, SwapOptions, SwapPartner,
} from '@/api/substitutions'
import HelpTip from '@/components/HelpTip.vue'

const message = useMessage()

const semesters = ref<{ id: number; label: string }[]>([])
const sid = ref<number | null>(null)
const leaves = ref<LeaveRequest[]>([])
const types = ref<Record<string, string>>({})
const openId = ref<number | null>(null) // 展开中的受影响节次
const rec = ref<Recommendation | null>(null)
const loadingRec = ref(false)
const countsHours = ref(true)
// 计费方式已简化:只分计入/不计入课时两种,跟著上面这个开关走,不再让选谁出钱。
// 代课单上印的计费方式 = 开关状态对应的「计入课时」/「不计入课时」。
const fundingOf = (counts: boolean): string => counts ? '计入课时' : '不计入课时'
const teachers = ref<Teacher[]>([])
// 调课:展开中节次的可对调清单。swapTeacherId 为空 = 只看也教这个班的老师
const swapOpen = ref(false)
const swap = ref<SwapOptions | null>(null)
const loadingSwap = ref(false)
const swapTeacherId = ref<number | null>(null)
// 找几周:换节次、换假单都沿用组长上次选的(常和隔三周调的学校,每次都要重选很烦)
const swapWeeks = ref(2)
const SWAP_WEEK_OPTIONS = [
  { label: '本周与下周', value: 2 },
  { label: '往后共 3 周', value: 3 },
  { label: '往后共 4 周', value: 4 },
]
// 一位老师两周内可换的节次常有二、三十个;先只列同班的,其他班收起来(展开过的老师记在这里)
const swapExpanded = ref<Set<number>>(new Set())

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
function withWeekday(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return `${iso}(${WEEKDAYS[new Date(y, m - 1, d).getDay()]})`
}
// 清单里一次列十几个日期,年份不必每个都重复
function shortDate(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return `${m}/${d}(${WEEKDAYS[new Date(y, m - 1, d).getDay()]})`
}

const semesterOptions = computed(() => semesters.value.map((s) => ({ label: s.label, value: s.id })))

// 只显示还有待处理节次的假单(已全部处理或已销假的收起来)
const activeLeaves = computed(() =>
  leaves.value.filter((l) => l.status === 'registered' && l.affected_count > 0))

async function reload() {
  if (!sid.value) return
  leaves.value = await listLeaves(sid.value)
}

function resetSwap() {
  swapOpen.value = false
  swap.value = null
  swapTeacherId.value = null
  swapExpanded.value = new Set()
}

/** 这位老师目前要显示的节次:有同班的就先只列同班,其他班等组长展开 */
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

async function onSemesterChange(id: number) {
  sid.value = id
  openId.value = null
  rec.value = null
  resetSwap()
  ;[teachers.value] = await Promise.all([listTeachers(id), reload()])
}

onMounted(async () => {
  const [sems, subTypes] = await Promise.all(
    [listSemesters(), listSubstitutionTypes()])
  ;[semesters.value, types.value] = [sems, subTypes]
  if (semesters.value.length) await onSemesterChange(semesters.value[0].id)
})

async function openPeriod(p: AffectedPeriod) {
  if (openId.value === p.id) {
    openId.value = null
    return
  }
  openId.value = p.id
  rec.value = null
  resetSwap()
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
      ? `已指派 ${candidate.teacher_name} ${types.value[type]}`
      : `已设为${types.value[type]}`)
    openId.value = null
    await reload()
  } catch (e) {
    message.error((e as ApiError).message || '指派失败')
  }
}

// 已处置的节次写出「怎么处置」:只写「→ 陈师」分不出是代课还是调课,
// 调课还得知道请假的老师哪天要回来补课
function dispositionText(l: LeaveRequest, p: AffectedPeriod): string {
  if (!p.sub_type) return p.handler_name ? `→ ${p.handler_name}` : ''
  const label = types.value[p.sub_type] ?? p.sub_type
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

// 代课单同时涵盖并班(纸本格子标[并])
function substituteIds(l: LeaveRequest): number[] {
  return l.affected_periods
    .filter((p) => (p.sub_type === 'substitute' || p.sub_type === 'merge')
      && p.status !== 'cancelled')
    .map((p) => p.id)
}

function printSlips(kind: 'swap' | 'substitute', ids: number[]) {
  if (sid.value) openSlips(kind, sid.value, ids)
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
    openId.value = null
    resetSwap()
    await reload()
  } catch (e) {
    message.error((e as ApiError).message || '调课失败')
  }
}

// 整批指派代课:班主任请整天或好几天假,同一位代课老师接下所有节次(外聘代课（按日计酬）常见)。
// 逐节点要点几十次;这里一次派完,派不成的节次(代课老师那节有课)列出来另外找人。
const batchShow = ref(false)
const batchLeave = ref<LeaveRequest | null>(null)
const batchTeacher = ref<number | null>(null)
const batchCounts = ref(true)
const batchDate = ref('') // 空字串 = 整张假单
const batchBusy = ref(false)
const batchSkipped = ref<BatchSkip[]>([])
const batchDone = ref<number | null>(null)

function pendingOf(l: LeaveRequest): AffectedPeriod[] {
  return l.affected_periods.filter((p) => p.status === 'pending')
}
const batchTeacherOptions = computed(() =>
  teachers.value
    .filter((t) => t.id !== batchLeave.value?.teacher_id && t.is_active)
    .map((t) => ({ label: t.name, value: t.id })))
const batchDateOptions = computed(() => {
  const l = batchLeave.value
  if (!l) return []
  const days = [...new Set(pendingOf(l).map((p) => p.date))].sort()
  return [
    { label: `整张假单(待处理 ${pendingOf(l).length} 节)`, value: '' },
    ...days.map((d) => ({
      label: `只派 ${withWeekday(d)}(${pendingOf(l).filter((p) => p.date === d).length} 节)`,
      value: d,
    })),
  ]
})
function openBatch(l: LeaveRequest) {
  batchLeave.value = l
  batchTeacher.value = null
  batchCounts.value = true
  batchDate.value = ''
  batchSkipped.value = []
  batchDone.value = null
  batchShow.value = true
}
async function runBatch() {
  if (!batchLeave.value || batchTeacher.value === null) return
  batchBusy.value = true
  try {
    const r = await assignSubstitutionBatch(batchLeave.value.id, {
      handler_teacher_id: batchTeacher.value,
      counts_toward_hours: batchCounts.value,
      funding_source: fundingOf(batchCounts.value),
      date: batchDate.value || null,
    })
    batchDone.value = r.assigned
    batchSkipped.value = r.skipped
    openId.value = null
    await reload()
    // 视窗还开著(列出没派成的节次)时,范围选单上的「待处理 N 节」要跟著更新
    const id = batchLeave.value.id
    batchLeave.value = leaves.value.find((l) => l.id === id) ?? batchLeave.value
    if (r.skipped.length === 0) {
      message.success(`已指派 ${r.assigned} 节代课`)
      batchShow.value = false
    }
  } catch (e) {
    message.error((e as ApiError).message || '指派失败')
  } finally {
    batchBusy.value = false
  }
}

async function undo(p: AffectedPeriod) {
  await clearSubstitution(p.id)
  message.info('已撤回处置,退回待处理')
  await reload()
}

const STATUS: Record<AffectedPeriod['status'], { type: string; label: string }> = {
  pending: { type: 'warning', label: '待处理' },
  resolved: { type: 'success', label: '已确认' },
  completed: { type: 'info', label: '已完成' },
  cancelled: { type: 'default', label: '已取消' },
}

function candidateTagType(c: Candidate): string {
  if (c.same_grade && c.same_subject) return 'success'
  if (c.same_grade || c.same_subject) return 'info'
  if (c.at_school_that_day) return 'info'
  return 'default'
}
</script>

<template>
  <!-- 视窗要放在 n-space 外面:n-space 会把每个子节点包一层没有 key 的 div,假单卡片数量一变,
       视窗就跟著换位置重挂,正式建置下会关不掉(v1.2.14 在「学期与节次表」踩过)。 -->
  <div>
    <div class="ios-page">
      <n-space align="center">
        <h1 class="ios-title">调代课处理</h1>
        <n-select
          :value="sid" :options="semesterOptions" style="width: 220px"
          placeholder="选择学期" @update:value="onSemesterChange"
        />
      </n-space>

      <n-empty v-if="!sid" description="请先建立学期" />
      <n-empty v-else-if="!activeLeaves.length" description="目前没有待处理的请假" />

      <template v-else>
        <section
          v-for="l in activeLeaves" :key="l.id" class="ios-section" data-testid="sub-leave"
        >
          <div class="ios-section-title">
            <span>{{ `${l.teacher_name} · ${l.leave_type_label} · 待处理 ${l.pending_count} 节` }}</span>
            <span
              v-if="pendingOf(l).length > 1 || swapIds(l).length || substituteIds(l).length"
            >
              <n-space size="small">
                <n-button
                  v-if="pendingOf(l).length > 1" size="small" type="primary" ghost
                  data-testid="sub-batch-open" @click="openBatch(l)"
                >
                  整批指派代课
                </n-button>
                <HelpTip v-if="pendingOf(l).length > 1" testid="help-sub-batch">把这张假单还没处理的节次一次指派给同一位代课老师，不用一节一节指。已经处理过的节次不会更动，代课老师自己有课的节次会跳过，留给你另外找人。</HelpTip>
                <n-button
                  v-if="swapIds(l).length" size="small" data-testid="sub-print-leave"
                  @click="printSlips('swap', swapIds(l))"
                >
                  打印调课单({{ swapIds(l).length }} 节)
                </n-button>
                <n-button
                  v-if="substituteIds(l).length" size="small" data-testid="sub-print-leave-sub"
                  @click="printSlips('substitute', substituteIds(l))"
                >
                  打印代课单({{ substituteIds(l).length }} 节)
                </n-button>
              </n-space>
            </span>
          </div>
          <div class="ios-card">
            <div class="ios-card-body">
          <n-space vertical size="small">
            <div v-for="p in l.affected_periods" :key="p.id" data-testid="sub-period">
              <n-space align="center" :wrap="false">
                <n-tag size="small" :type="STATUS[p.status].type as never">
                  {{ STATUS[p.status].label }}
                </n-tag>
                <n-text style="min-width: 260px">
                  {{ withWeekday(p.date) }} {{ p.period_name }} ·
                  {{ p.class_names }} {{ p.subject_name }}
                  <n-text v-if="p.room_name" depth="3">@{{ p.room_name }}</n-text>
                </n-text>
                <n-text
                  v-if="p.sub_type || p.handler_name" type="success" data-testid="sub-handler"
                >
                  {{ dispositionText(l, p) }}
                </n-text>
                <n-button
                  v-if="p.status === 'pending'" size="small" type="primary"
                  data-testid="sub-handle" @click="openPeriod(p)"
                >
                  {{ openId === p.id ? '收合' : '处理' }}
                </n-button>
                <n-button
                  v-else-if="p.status === 'resolved'" size="small" tertiary
                  data-testid="sub-undo" @click="undo(p)"
                >
                  撤回
                </n-button>
                <n-button
                  v-if="p.sub_type === 'swap' && p.status !== 'cancelled'" size="small" tertiary
                  data-testid="sub-print-slip" @click="printSlips('swap', [p.id])"
                >
                  打印调课单
                </n-button>
                <n-button
                  v-if="(p.sub_type === 'substitute' || p.sub_type === 'merge')
                    && p.status !== 'cancelled'"
                  size="small" tertiary
                  data-testid="sub-print-slip-sub" @click="printSlips('substitute', [p.id])"
                >
                  打印代课单
                </n-button>
              </n-space>

              <!-- 展开:代课推荐 + 其他处置 -->
              <div
                v-if="openId === p.id" class="ios-card" style="margin: 8px 0 8px 40px"
                data-testid="sub-panel"
              >
                <div class="ios-card-body">
                <n-space vertical size="small">
                  <n-text v-if="loadingRec" depth="3">计算可代教师中…</n-text>

                  <template v-else-if="rec">
                    <n-alert
                      v-if="!rec.candidates.length" type="warning" :bordered="false"
                      data-testid="sub-nocandidate"
                    >
                      {{ rec.no_candidate_hint }}
                    </n-alert>

                    <template v-else>
                      <n-space align="center">
                        <n-text depth="3">代课课时</n-text>
                        <HelpTip testid="help-sub-counts">计入：这节代课算进代课课时统计；不计：只是替上课，不算代课工作量。这个开关只影响代课课时统计，不影响仪表板上的已上总数——实际上了课，仪表板都计。</HelpTip>
                        <n-switch v-model:value="countsHours" size="small" />
                        <n-text depth="3">{{ countsHours ? '计入' : '不计' }}</n-text>
                      </n-space>
                      <div
                        v-for="c in rec.candidates" :key="c.teacher_id"
                        data-testid="sub-candidate"
                      >
                        <n-space align="center" :wrap="false">
                          <n-button
                            size="small" type="primary" ghost
                            data-testid="sub-pick" @click="assign(p, 'substitute', c)"
                          >
                            指派 {{ c.teacher_name }}
                          </n-button>
                          <n-tag size="small" :type="candidateTagType(c) as never">
                            {{ c.reasons.join(' · ') }}
                          </n-tag>
                        </n-space>
                      </div>
                    </template>
                  </template>

                  <n-space size="small" style="margin-top: 8px">
                    <n-text depth="3">或改采:</n-text>
                    <HelpTip testid="help-sub-alt">调课：请另一位老师来上这一节，请假老师往后找一天补回对方一节，不计代课课时。并班：两个班合到一节上。自习：学生自习，不安排老师。不处理：这节直接停课，不安排人。</HelpTip>
                    <n-button
                      size="tiny" :type="swapOpen ? 'primary' : 'default'"
                      data-testid="sub-swap" @click="toggleSwap(p)"
                    >
                      调课
                    </n-button>
                    <n-button size="tiny" data-testid="sub-merge" @click="assign(p, 'merge')">
                      并班
                    </n-button>
                    <n-button
                      size="tiny" data-testid="sub-selfstudy" @click="assign(p, 'self_study')"
                    >
                      自习
                    </n-button>
                    <n-button size="tiny" data-testid="sub-cancel" @click="assign(p, 'cancel')">
                      不处理
                    </n-button>
                  </n-space>

                  <!-- 调课:乙来上这一节,甲在往后几周内补回乙的一节 -->
                  <div v-if="swapOpen" class="swap" data-testid="sub-swap-panel">
                    <n-text depth="3" class="swap-intro">
                      调课 = 请另一位老师来上这一节,{{ l.teacher_name }}再找一天补回对方的一节(不计代课课时)。
                      <template v-if="swap">
                        以下是 {{ shortDate(swap.date_from) }} 到 {{ shortDate(swap.date_to) }}
                        之间,双方都有空的节次,点一下就成立。
                      </template>
                    </n-text>
                    <n-space align="center" size="small" style="margin-bottom: 6px">
                      <n-select
                        :value="swapTeacherId" :options="swapTeacherOptions(l)" filterable clearable
                        size="small" style="width: 200px" placeholder="只看也教这班的老师"
                        data-testid="sub-swap-teacher"
                        @update:value="(v: number | null) => onSwapTeacherChange(p, v)"
                      />
                      <n-text depth="3">也可以指定其他老师</n-text>
                      <n-text depth="3" style="margin-left: 12px">范围</n-text>
                      <n-select
                        :value="swapWeeks" :options="SWAP_WEEK_OPTIONS" size="small"
                        style="width: 140px" data-testid="sub-swap-weeks"
                        @update:value="(v: number) => onSwapWeeksChange(p, v)"
                      />
                    </n-space>

                    <n-text v-if="loadingSwap" depth="3">寻找可对调的节次…</n-text>
                    <template v-else-if="swap">
                      <n-alert
                        v-if="!swap.partners.length" type="info" :bordered="false"
                        data-testid="sub-swap-empty"
                      >
                        {{ swapTeacherId
                          ? '这位老师目前无法对调(可能已停用)。'
                          : '没有其他老师也教这个班,可以从上方指定一位老师看看。' }}
                      </n-alert>
                      <div
                        v-for="partner in swap.partners" :key="partner.teacher_id"
                        class="swap-partner" data-testid="sub-swap-partner"
                      >
                        <n-space align="center" size="small">
                          <b>{{ partner.teacher_name }}</b>
                          <n-tag v-if="partner.teaches_same_class" size="small" type="success">
                            也教这班
                          </n-tag>
                        </n-space>
                        <n-text v-if="partner.blocked_reason" depth="3" class="swap-note">
                          无法对调:{{ partner.blocked_reason }}
                        </n-text>
                        <n-text v-else-if="!partner.options.length" depth="3" class="swap-note">
                          这段期间找不到双方都有空的节次,可试著放宽周数
                        </n-text>
                        <n-space v-else size="small" class="swap-note">
                          <n-button
                            v-for="opt in visibleOptions(partner)"
                            :key="`${opt.entry_id}-${opt.date}-${opt.period_no}`"
                            size="small" :type="opt.same_class ? 'primary' : 'default'" ghost
                            data-testid="sub-swap-option" @click="assignSwap(l, p, partner, opt)"
                          >
                            {{ shortDate(opt.date) }} {{ opt.period_name }} ·
                            {{ opt.class_names }} {{ opt.subject_name }}
                            <span v-if="opt.in_block" class="swap-block">(连堂之一)</span>
                          </n-button>
                          <n-button
                            v-if="hiddenCount(partner)" size="small" text type="primary"
                            data-testid="sub-swap-more" @click="expandPartner(partner)"
                          >
                            显示其他班级的 {{ hiddenCount(partner) }} 个节次
                          </n-button>
                        </n-space>
                      </div>
                    </template>
                  </div>
                </n-space>
                </div>
              </div>
            </div>
          </n-space>
            </div>
          </div>
        </section>
      </template>
    </div>

    <n-modal
      v-model:show="batchShow" preset="card" style="max-width: 560px"
      :title="`整批指派代课:${batchLeave?.teacher_name ?? ''}`" data-testid="sub-batch"
    >
      <n-space vertical>
        <n-text depth="3">
          把这张假单还没处理的节次,一次指派给同一位代课老师。已经处理过的节次不会更动;
          代课老师自己有课的节次会跳过,并列出来让你另外找人。
        </n-text>
        <n-space align="center">
          <n-text style="min-width: 70px">代课老师</n-text>
          <n-select
            v-model:value="batchTeacher" :options="batchTeacherOptions" filterable
            placeholder="选择教师" style="width: 240px" data-testid="sub-batch-teacher"
          />
        </n-space>
        <n-space align="center">
          <n-text style="min-width: 70px">代课课时</n-text>
          <n-switch v-model:value="batchCounts" size="small" />
          <n-text depth="3">{{ batchCounts ? '计入' : '不计' }}</n-text>
        </n-space>
        <n-space align="center">
          <n-text style="min-width: 70px">范围</n-text>
          <n-select
            v-model:value="batchDate" :options="batchDateOptions"
            style="width: 320px" data-testid="sub-batch-date"
          />
        </n-space>

        <n-alert
          v-if="batchSkipped.length" type="warning" :show-icon="true"
          :title="`已指派 ${batchDone} 节;有 ${batchSkipped.length} 节没有派成`"
          data-testid="sub-batch-skipped"
        >
          <ul class="batch-skips">
            <li v-for="s in batchSkipped" :key="s.affected_period_id" data-testid="sub-batch-skip">
              {{ withWeekday(s.date) }} {{ s.period_name }} · {{ s.class_names }} {{ s.subject_name }}
              ——{{ s.reason }}
            </li>
          </ul>
          这几节仍是「待处理」,请关闭视窗后个别处理。
        </n-alert>

        <n-space justify="end">
          <n-button data-testid="sub-batch-close" @click="batchShow = false">
            {{ batchSkipped.length ? '关闭' : '取消' }}
          </n-button>
          <n-button
            v-if="!batchSkipped.length" type="primary" :loading="batchBusy"
            :disabled="batchTeacher === null" data-testid="sub-batch-run" @click="runBatch"
          >
            指派
          </n-button>
        </n-space>
      </n-space>
    </n-modal>
  </div>
</template>

<style scoped>
.batch-skips { margin: 4px 0 6px; padding-left: 20px; }
.swap { margin-top: 8px; padding-top: 8px; border-top: 1px dashed rgba(128, 128, 128, 0.35); }
.swap-intro { display: block; margin-bottom: 6px; }
.swap-partner { margin: 6px 0; }
.swap-note { display: block; margin: 4px 0 0 12px; }
.swap-block { margin-left: 4px; opacity: 0.7; }
</style>
