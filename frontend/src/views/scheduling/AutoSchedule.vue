<script setup lang="ts">
import {
  NAlert, NButton, NCard, NCheckbox, NCheckboxGroup, NEmpty, NInputNumber, NPopconfirm, NProgress,
  NSelect, NSpace, NTag, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import { listSemesters } from '@/api/semesters'
import type { SemesterListItem } from '@/api/semesters'
import {
  cancelSolveJob, getSolveJob, listRelaxable, listSolveJobs, preflight, startAutoSchedule, stopSolveJob,
} from '@/api/solver'
import type {
  PreflightIssue, PreflightReport, RelaxableOption, SolveJob,
} from '@/api/solver'
import { listTimetables } from '@/api/timetables'
import type { TimetableBrief } from '@/api/timetables'

const message = useMessage()
const router = useRouter()

const POLL_MS = 2000

const semesters = ref<SemesterListItem[]>([])
const sid = ref<number | null>(null)
const drafts = ref<TimetableBrief[]>([])
const sourceId = ref<number | null>(null)
const minutes = ref(10) // timeout 默认 10 分钟

const check = ref<PreflightReport | null>(null)
const job = ref<SolveJob | null>(null)
const history = ref<SolveJob[]>([])
const blockingIssues = ref<PreflightIssue[]>([])
const starting = ref(false)

const relaxable = ref<RelaxableOption[]>([])
const allowPartial = ref(false)
const relax = ref<string[]>([])

let timer: ReturnType<typeof setInterval> | null = null

const semesterOptions = computed(() => semesters.value.map((s) => ({ label: s.label, value: s.id })))
const draftOptions = computed(() =>
  drafts.value.map((t) => ({ label: `${t.name}(${t.entry_count} 格)`, value: t.id })))

const running = computed(() => job.value?.status === 'queued' || job.value?.status === 'running')
const explaining = computed(() => running.value && job.value?.phase === 'explaining')
const conflict = computed(() => job.value?.conflict ?? null)
const conflictCauses = computed(() => conflict.value?.causes ?? [])
const unscheduled = computed(() => job.value?.unscheduled ?? [])

// 进行中显示「已用掉多少时间预算」;结束后一律填满——提前结束时 elapsed 可能只有 1%,
// 进度条停在最左边却写著「已完成」会让人以为排坏了。
const progressPercent = computed(() => {
  if (!job.value) return 0
  if (!running.value) return 100
  return Math.min(100, Math.round((job.value.elapsed / job.value.max_seconds) * 100))
})

const statusTagType = computed(() => {
  if (running.value) return 'info'
  if (job.value?.status === 'finished') return 'success'
  if (job.value?.status === 'cancelled') return 'warning'
  return 'error'
})

const STATUS_LABELS: Record<string, string> = {
  queued: '排队中', running: '排课中', finished: '已完成', failed: '失败', cancelled: '已取消',
}
const statusLabel = computed(() =>
  (explaining.value ? '定位无解原因中' : STATUS_LABELS[job.value?.status ?? ''] ?? ''))

const codeName = (code: string) => relaxable.value.find((o) => o.code === code)?.name ?? code

// 有试解在时限内没判定出来。each 的每一项仍是验证过的,只是清单可能不全;
// joint 则连「这组是不是最小」都没把握。两者要说不同的话。
const incompleteNote = computed(() => {
  if (conflict.value?.mode === 'joint') return '(时间有限,这组未必是最小的组合)'
  return '(时间有限,可能还有其他原因未列出)'
})

const elapsedText = computed(() => {
  const s = job.value?.elapsed ?? 0
  return s < 1 ? '不到 1 秒' : `${Math.round(s)} 秒`
})
const unplacedPeriods = computed(() => unscheduled.value.reduce((n, u) => n + u.periods, 0))

function stopPolling() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}
onUnmounted(stopPolling)

const isActive = (j: SolveJob) => j.status === 'queued' || j.status === 'running'

function tagTypeFor(j: SolveJob) {
  if (isActive(j)) return 'info'
  if (j.status === 'finished') return 'success'
  if (j.status === 'cancelled') return 'warning'
  return 'error'
}

function labelFor(j: SolveJob) {
  if (isActive(j) && j.phase === 'explaining') return '定位无解原因中'
  return STATUS_LABELS[j.status] ?? j.status
}

function fmtTime(ts: number) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

/** 把某个任务装进「排课进度」卡:进行中的顺带接上轮询。 */
function attachJob(j: SolveJob) {
  job.value = j
  stopPolling()
  if (isActive(j)) timer = setInterval(poll, POLL_MS)
}

/** 拉本学期的任务列表;有进行中的任务而进度卡没在跟它,就自动接回。 */
async function loadHistory() {
  if (!sid.value) return
  try {
    history.value = await listSolveJobs(sid.value)
  } catch {
    history.value = []
    return
  }
  const active = history.value.find(isActive)
  if (active && (!job.value || job.value.job_id === active.job_id || !isActive(job.value))) {
    if (job.value?.job_id !== active.job_id) attachJob(active)
  }
}

function selectJob(j: SolveJob) {
  attachJob(j)
}

async function reload() {
  if (!sid.value) return
  const all = await listTimetables(sid.value)
  drafts.value = all.filter((t) => t.status === 'draft')
  sourceId.value = drafts.value[0]?.id ?? null
  check.value = await preflight(sid.value)
  await loadHistory()
}

async function onSemesterChange(id: number) {
  sid.value = id
  job.value = null
  blockingIssues.value = []
  stopPolling()
  await reload()
}

onMounted(async () => {
  ;[semesters.value, relaxable.value] = await Promise.all([listSemesters(), listRelaxable()])
  if (semesters.value.length) await onSemesterChange(semesters.value[0].id)
})

async function poll() {
  if (!job.value) return
  try {
    job.value = await getSolveJob(job.value.job_id)
  } catch {
    stopPolling()
    return
  }
  if (!running.value) {
    stopPolling()
    if (job.value.status === 'finished') message.success(`已产生「${job.value.result_name}」`)
    if (job.value.status === 'cancelled') message.info('已取消排课')
    if (job.value.status === 'failed') message.error(job.value.error ?? '排课失败')
    await reload()
  }
}

async function onStart() {
  if (!sourceId.value) return
  starting.value = true
  blockingIssues.value = []
  try {
    const { job_id } = await startAutoSchedule(sourceId.value, minutes.value * 60, {
      allowPartial: allowPartial.value,
      relax: allowPartial.value ? relax.value : [],
    })
    attachJob(await getSolveJob(job_id))
    await loadHistory()
  } catch (e) {
    const detail = (e as ApiError).detail as unknown
    if (detail && typeof detail === 'object' && 'issues' in detail) {
      blockingIssues.value = (detail as { issues: PreflightIssue[] }).issues
      message.error('资料未通过排课前置检查')
    } else {
      message.error((e as ApiError).message || '无法启动排课')
    }
  } finally {
    starting.value = false
  }
}

/** 照著冲突报告的建议重试:勾好可放宽的项目,直接再排一次。 */
async function onRetryPartial() {
  allowPartial.value = true
  relax.value = conflict.value?.relaxable_codes ?? []
  job.value = null
  await onStart()
}

async function onStop() {
  if (!job.value) return
  await stopSolveJob(job.value.job_id)
  message.info('已要求提前结束,将保留目前最佳解')
}
async function onCancel() {
  if (!job.value) return
  await cancelSolveJob(job.value.job_id)
  message.info('已要求取消')
}

function openResult() {
  router.push({ name: 'versions' })
}
</script>

<template>
  <n-space vertical size="large">
    <n-space align="center">
      <h2 style="margin: 0">自动排课</h2>
      <n-select
        :value="sid" :options="semesterOptions" style="width: 220px"
        placeholder="选择学期" @update:value="onSemesterChange"
      />
    </n-space>

    <n-empty v-if="!sid" description="请先建立学期" />

    <template v-else>
      <!-- 排课前置检查 -->
      <n-card v-if="check" title="排课前置检查" size="small">
        <n-space vertical>
          <n-text depth="3">
            {{ check.class_count }} 班 · {{ check.teacher_count }} 位教师 ·
            {{ check.assignment_count }} 笔配课 · 共 {{ check.total_periods }} 节
          </n-text>
          <n-alert v-if="check.ok && check.warning_count === 0" type="success" :bordered="false">
            资料检查通过,可以开始排课
          </n-alert>
          <n-alert v-else :type="check.ok ? 'warning' : 'error'" :bordered="false">
            {{ check.error_count }} 项错误、{{ check.warning_count }} 项提醒
          </n-alert>
          <div v-for="i in check.issues" :key="i.code + i.subject_id" data-testid="pf-issue">
            <n-tag size="small" :type="i.level === 'error' ? 'error' : 'warning'">
              {{ i.level === 'error' ? '错误' : '提醒' }}
            </n-tag>
            <n-text style="margin-left: 8px">{{ i.message }}</n-text>
          </div>
        </n-space>
      </n-card>

      <!-- 启动 -->
      <n-card title="开始排课" size="small">
        <n-space vertical>
          <n-space align="center">
            <n-text>来源草稿</n-text>
            <n-select
              v-model:value="sourceId" :options="draftOptions" style="width: 260px"
              placeholder="选择草稿" data-testid="as-source" :disabled="running"
            />
            <n-text>排课时间上限</n-text>
            <n-input-number
              v-model:value="minutes" :min="1" :max="60" style="width: 120px"
              :disabled="running" data-testid="as-minutes"
            >
              <template #suffix>分钟</template>
            </n-input-number>
            <n-button
              type="primary" :loading="starting" :disabled="!sourceId || running"
              data-testid="as-start" @click="onStart"
            >
              开始排课
            </n-button>
          </n-space>
          <n-text depth="3">
            锁定的格位会维持原位;其余已排的课会作为求解起点,结果写成新草稿,来源草稿不动。
          </n-text>

          <n-checkbox v-model:checked="allowPartial" :disabled="running" data-testid="as-partial">
            允许部分排课(排不下的课列成清单,不要整个失败)
          </n-checkbox>
          <n-space v-if="allowPartial" align="center" style="padding-left: 24px">
            <n-text depth="3">可放宽:</n-text>
            <n-checkbox-group v-model:value="relax" :disabled="running">
              <n-checkbox
                v-for="o in relaxable" :key="o.code" :value="o.code"
                :label="o.name" :data-testid="`as-relax-${o.code}`"
              />
            </n-checkbox-group>
          </n-space>
          <n-text v-if="allowPartial" depth="3" style="padding-left: 24px">
            班级、教师、场地的「同时段只能有一门课」不可放宽——那是物理限制,不是政策。
          </n-text>

          <n-alert v-if="blockingIssues.length" type="error" title="请先修正这些问题">
            <div v-for="i in blockingIssues" :key="i.code + i.subject_id" data-testid="as-blocking">
              {{ i.message }}
            </div>
          </n-alert>
        </n-space>
      </n-card>

      <!-- 进度 -->
      <n-card v-if="job" title="排课进度" size="small" data-testid="as-job">
        <n-space vertical>
          <n-space align="center">
            <n-tag :type="statusTagType" data-testid="as-status">{{ statusLabel }}</n-tag>
            <n-text>已耗时 {{ elapsedText }} / 上限 {{ job.max_seconds }} 秒</n-text>
            <n-text v-if="running || job.solutions" data-testid="as-solutions">
              已找到 {{ job.solutions }} 个解
            </n-text>
            <!-- 部分排课的目标值被「未排入」的高额惩罚灌爆(一节 = 10000),
                 拿给人看只会以为排坏了;真正该看的是未排几节。 -->
            <n-text v-if="job.partial && !running">未排 {{ unplacedPeriods }} 节</n-text>
            <n-text v-else-if="job.objective !== null">目前目标值 {{ Math.round(job.objective) }}</n-text>
          </n-space>

          <n-progress
            type="line" :percentage="progressPercent"
            :status="job.status === 'failed' ? 'error'
              : job.status === 'cancelled' ? 'warning'
                : running ? 'default' : 'success'"
            :processing="running"
          />

          <n-space v-if="running && !explaining">
            <n-button
              type="primary" ghost :disabled="job.solutions === 0"
              data-testid="as-stop" @click="onStop"
            >
              提前结束(取目前最佳解)
            </n-button>
            <n-popconfirm @positive-click="onCancel">
              <template #trigger>
                <n-button type="error" ghost data-testid="as-cancel">取消排课</n-button>
              </template>
              取消后不会产生结果草稿,确定?
            </n-popconfirm>
          </n-space>

          <n-text v-if="explaining" depth="3" data-testid="as-explaining">
            排不出来。正在逐项试解,找出是哪几件事凑在一起造成的……
          </n-text>

          <!-- 定位不出具体原因时(例如硬约束其实可解、只是软约束最佳化太慢),仍要给一句人话 -->
          <n-alert
            v-if="job.status === 'failed' && !conflictCauses.length"
            type="error" data-testid="as-error"
          >
            {{ job.error }}
          </n-alert>

          <!-- 无解冲突定位:不只说「排不出来」,说是谁、差几节、松开哪一个就好 -->
          <n-alert
            v-if="conflict && conflictCauses.length" type="error"
            :title="conflict.headline" data-testid="as-conflict"
          >
            <n-space vertical size="small">
              <div v-for="(c, k) in conflictCauses" :key="k" data-testid="as-cause">
                <n-tag size="small" :bordered="false" :type="c.relaxable ? 'warning' : 'error'">
                  {{ c.scope_name }}
                </n-tag>
                <n-text style="margin-left: 8px">{{ c.message }}</n-text>
                <div style="padding-left: 8px">
                  <n-text depth="3">建议:{{ c.suggestion }}</n-text>
                </div>
              </div>
              <n-text v-if="!conflict.complete" depth="3">{{ incompleteNote }}</n-text>
              <n-button
                v-if="conflict.relaxable_codes.length" type="primary" ghost size="small"
                data-testid="as-retry-partial" @click="onRetryPartial"
              >
                改用部分排课(放宽{{ conflict.relaxable_codes.map(codeName).join('、') }})
              </n-button>
            </n-space>
          </n-alert>

          <n-alert v-if="job.status === 'finished'" type="success" data-testid="as-done">
            已产生新草稿「{{ job.result_name }}」
            <n-button text type="primary" style="margin-left: 8px" @click="openResult">
              前往版本与发布
            </n-button>
          </n-alert>

          <!-- 未排清单:部分排课的另一半交付物 -->
          <n-alert
            v-if="unscheduled.length" type="warning" title="以下课务未能排入,请人工处理"
            data-testid="as-unscheduled"
          >
            <table class="data-table">
              <thead>
                <tr><th>科目</th><th>班级</th><th>未排节数</th><th>原因</th></tr>
              </thead>
              <tbody>
                <tr v-for="u in unscheduled" :key="u.assignment_ids.join('-')">
                  <td>{{ u.subject_name }}</td>
                  <td>{{ u.class_names.join('、') }}</td>
                  <td>{{ u.periods }} 节</td>
                  <!-- 完全排不下的课会说明原因;其余是 solver 权衡后的取舍 -->
                  <td>{{ u.reason || '排课时权衡取舍' }}</td>
                </tr>
              </tbody>
            </table>
          </n-alert>

          <!-- 软约束达成度 -->
          <table v-if="job.report" class="data-table" data-testid="as-report">
            <thead>
              <tr><th>软约束</th><th>权重</th><th>达成</th><th>未达成明细</th></tr>
            </thead>
            <tbody>
              <tr v-for="i in job.report.items" :key="i.code">
                <td>{{ i.code }} {{ i.name }}</td>
                <td>{{ i.weight === 0 ? '关闭' : i.weight }}</td>
                <td>
                  {{ i.satisfied }} / {{ i.opportunities }}
                  <n-text :depth="3">({{ Math.round(i.rate * 100) }}%)</n-text>
                </td>
                <td>
                  <n-text v-if="!i.details.length" depth="3">—</n-text>
                  <div v-for="(d, k) in i.details.slice(0, 3)" v-else :key="k">{{ d }}</div>
                  <n-text v-if="i.details.length > 3" depth="3">
                    …等 {{ i.violations }} 项
                  </n-text>
                </td>
              </tr>
            </tbody>
          </table>
        </n-space>
      </n-card>

      <!-- 排课记录:离开页面再回来,靠它找回进行中的任务与过去的结果(保留 24 小时) -->
      <n-card title="排课记录" size="small" data-testid="as-history">
        <n-space vertical size="small">
          <n-text v-if="!history.length" depth="3">尚无排课记录(记录保留 24 小时)</n-text>
          <div
            v-for="j in history" :key="j.job_id" data-testid="as-history-row"
            :style="{
              cursor: 'pointer', padding: '6px 8px', borderRadius: '4px',
              background: job?.job_id === j.job_id ? 'rgba(128,128,128,0.12)' : 'transparent',
            }"
            @click="selectJob(j)"
          >
            <n-space align="center" :size="8">
              <n-text depth="3">{{ fmtTime(j.created_at) }}</n-text>
              <n-tag size="small" :type="tagTypeFor(j)">{{ labelFor(j) }}</n-tag>
              <n-text>来源:{{ j.source_name }}</n-text>
              <n-text v-if="j.solutions" depth="3">{{ j.solutions }} 个解</n-text>
              <n-text v-if="j.status === 'finished' && j.result_name" depth="3">
                结果:{{ j.result_name }}
              </n-text>
              <n-text v-if="j.status === 'failed' && j.error" depth="3">
                {{ j.error.slice(0, 40) }}
              </n-text>
            </n-space>
          </div>
        </n-space>
      </n-card>
    </template>
  </n-space>
</template>

<style scoped>
.data-table { border-collapse: collapse; width: 100%; }
.data-table th, .data-table td {
  border: 1px solid var(--n-border-color, #e0e0e0); padding: 6px 10px; text-align: left;
  vertical-align: top;
}
.data-table th { background: rgba(128, 128, 128, 0.08); font-weight: 600; }
</style>
