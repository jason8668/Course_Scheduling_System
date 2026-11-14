<script setup lang="ts">
import {
  NAlert, NButton, NEmpty, NInput, NSelect, NSpace, NSwitch, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import {
  NOTIFICATION_STATUSES, NOTIFICATION_TYPES,
  canResendNotification, formatNotifyResult, getExam, getNotificationSettings,
  getScoreProgress, getScoreSettings, listNotifications, notifyInvigilation,
  notifySchedule, notifyScoreDeadline, remindDueNotifications,
  resendNotification, saveNotificationSettings, summarizeUnsubmittedScores,
} from '@/api/exam'
import type { ExamNotification, NotifyResult } from '@/api/exam'
import { useAuthStore } from '@/stores/auth'

const message = useMessage()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const examId = Number(route.params.id)
// 发送与重发只限 admin/director 写,越权时后端回 403,前端原样展示。
const canManage = computed(() => auth.hasRole('admin') || auth.hasRole('director'))

const examName = ref('')
const loading = ref(false)
const forbidden = ref(false)

function goBack() {
  void router.push({ name: 'exam-exam-detail', params: { id: examId } })
}

function goHealth() {
  void router.push({ name: 'system' })
}

// ── 通知设置(KW-57~59):三类开关,默认全开 ──
const settingsForm = ref({
  schedule_notify_enabled: true,
  invigilation_remind_enabled: true,
  score_deadline_remind_enabled: true,
})
async function reloadSettings() {
  try {
    const s = await getNotificationSettings(examId)
    settingsForm.value = {
      schedule_notify_enabled: s.schedule_notify_enabled,
      invigilation_remind_enabled: s.invigilation_remind_enabled,
      score_deadline_remind_enabled: s.score_deadline_remind_enabled,
    }
  } catch (e) {
    message.error((e as ApiError).detail || '通知设置加载失败')
  }
}
async function saveSettings() {
  try {
    await saveNotificationSettings(examId, { ...settingsForm.value })
    message.success('通知设置已保存')
  } catch (e) {
    message.error((e as ApiError).detail || '保存失败')
  }
}

// ── 手动发送:四类通知 + 到期扫,结果只展示 sent/failed ──
const sending = ref<string | null>(null)
const lastResult = ref<{ kind: string; result: NotifyResult } | null>(null)
async function sendOne(kind: string, fn: () => Promise<NotifyResult>, label: string) {
  if (sending.value) return
  sending.value = kind
  try {
    const res = await fn()
    lastResult.value = { kind, result: res }
    message.success(`${label}:${formatNotifyResult(res)}`)
    await reloadLogs()
  } catch (e) {
    message.error((e as ApiError).detail || '发送失败')
  } finally {
    sending.value = null
  }
}
function resultText(kind: string): string {
  if (!lastResult.value || lastResult.value.kind !== kind) return ''
  return formatNotifyResult(lastResult.value.result)
}

// ── 录分截止提醒(KW-59):未录完情况以后端录分进度为准;截止时间取成绩设置 ──
const scoreDeadline = ref<string | null>(null)
const unsubmitted = ref({ unsubmittedClasses: 0, unsubmittedStudents: 0 })
async function reloadScoreState() {
  try {
    const [settings, progress] = await Promise.all([
      getScoreSettings(examId), getScoreProgress(examId),
    ])
    scoreDeadline.value = settings.score_deadline
    unsubmitted.value = summarizeUnsubmittedScores(progress)
  } catch {
    // 录分进度读不到时不阻断通知页,只不展示未录完数
    unsubmitted.value = { unsubmittedClasses: 0, unsubmittedStudents: 0 }
  }
}

// ── 通知记录(KW-61):按类型/状态/关键词筛选,失败可重发 ──
const filterType = ref<string | null>(null)
const filterStatus = ref<string | null>(null)
const filterQ = ref('')
const typeOptions = NOTIFICATION_TYPES.map((t) => ({ label: t, value: t }))
const statusOptions = NOTIFICATION_STATUSES.map((s) => ({ label: s, value: s }))
const logs = ref<ExamNotification[]>([])
const logTotal = ref(0)
const logsLoading = ref(false)
async function reloadLogs() {
  logsLoading.value = true
  try {
    const res = await listNotifications(examId, {
      type: filterType.value,
      status: filterStatus.value,
      q: filterQ.value || undefined,
    })
    logs.value = res.items
    logTotal.value = res.total
  } catch (e) {
    message.error((e as ApiError).detail || '通知记录加载失败')
  } finally {
    logsLoading.value = false
  }
}
async function onResend(log: ExamNotification) {
  try {
    const res = await resendNotification(examId, log.id)
    message.success(res.sent ? '重发成功' : `重发失败,状态:${res.status}`)
    await reloadLogs()
  } catch (e) {
    message.error((e as ApiError).detail || '重发失败')
  }
}
function fmtTime(s: string | null): string {
  if (!s) return '—'
  return s.replace('T', ' ').slice(0, 16)
}

onMounted(async () => {
  loading.value = true
  try {
    const exam = await getExam(examId)
    examName.value = exam.name
    await Promise.all([reloadSettings(), reloadScoreState(), reloadLogs()])
  } catch (e) {
    if ((e as ApiError).status === 403) forbidden.value = true
    else message.error((e as ApiError).detail || '加载失败')
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="ios-page">
    <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap">
      <n-button text type="primary" @click="goBack">← 考试详情</n-button>
      <h1 class="ios-title">{{ examName ? `${examName} · 通知与提醒` : '通知与提醒' }}</h1>
    </div>

    <n-alert v-if="forbidden" type="error" style="margin-top: 16px">
      无权查看该考试(不在你的可见范围内)。
    </n-alert>
    <n-empty v-else-if="!loading && !examName" description="找不到该考试" style="margin-top: 24px" />

    <template v-else-if="examName">
      <!-- 通知设置(KW-57~61) -->
      <div class="ios-section">
        <div class="ios-section-title">通知设置</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            四类通知默认全部开启;关掉后对应的手动发送与到期扫都不再发送。
          </n-text>
          <n-space vertical>
            <n-space align="center">
              <n-switch v-model:value="settingsForm.schedule_notify_enabled" :disabled="!canManage" />
              <n-text>考试日程通知</n-text>
            </n-space>
            <n-space align="center">
              <n-switch v-model:value="settingsForm.invigilation_remind_enabled" :disabled="!canManage" />
              <n-text>监考提醒</n-text>
            </n-space>
            <n-space align="center">
              <n-switch v-model:value="settingsForm.score_deadline_remind_enabled" :disabled="!canManage" />
              <n-text>录分截止提醒</n-text>
            </n-space>
          </n-space>
          <n-button
            v-if="canManage" type="primary" style="margin-top: 12px"
            data-testid="notifications-save-settings" @click="saveSettings"
          >保存设置</n-button>
        </div></div>
      </div>

      <!-- 考试日程通知(KW-57) -->
      <div class="ios-section">
        <div class="ios-section-title">考试日程通知</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            考试发布后,向班主任和任课教师发送钉钉个人通知(考试时间、科目安排),不发群消息。
          </n-text>
          <n-button
            v-if="canManage" type="primary" :loading="sending === 'schedule'"
            data-testid="notifications-send-schedule"
            @click="sendOne('schedule', () => notifySchedule(examId), '考试日程通知')"
          >发送考试日程通知</n-button>
          <n-text v-if="resultText('schedule')" style="display: block; margin-top: 8px" data-testid="notifications-result-schedule">
            {{ resultText('schedule') }}
          </n-text>
        </div></div>
      </div>

      <!-- 监考提醒(KW-58) -->
      <div class="ios-section">
        <div class="ios-section-title">监考提醒</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            监考安排发布后通知到监考教师本人;考前一天和当天开考前再提醒一次,提前量可由教师在个人设置中调整。
            到期扫为全校范围,同一提醒 24 小时内不重复发。
          </n-text>
          <n-space :wrap="true">
            <n-button
              v-if="canManage" type="primary" :loading="sending === 'invigilation'"
              data-testid="notifications-send-invigilation"
              @click="sendOne('invigilation', () => notifyInvigilation(examId), '监考提醒')"
            >发送监考提醒</n-button>
            <n-button
              v-if="canManage" :loading="sending === 'remind-due'"
              data-testid="notifications-remind-due"
              @click="sendOne('remind-due', () => remindDueNotifications(), '到期扫')"
            >执行到期扫</n-button>
          </n-space>
          <n-text v-if="resultText('invigilation')" style="display: block; margin-top: 8px" data-testid="notifications-result-invigilation">
            {{ resultText('invigilation') }}
          </n-text>
          <n-text v-if="resultText('remind-due')" style="display: block; margin-top: 8px" data-testid="notifications-result-remind-due">
            {{ resultText('remind-due') }}
          </n-text>
        </div></div>
      </div>

      <!-- 录分截止提醒(KW-59) -->
      <div class="ios-section">
        <div class="ios-section-title">录分截止提醒</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            临近录分截止时间,对未录完/未提交的教师自动发送个人催录提醒,教务可手动再催一次。
            录分截止时间在建考或成绩阶段设置;未设置截止时间时后端不发送催录提醒。
          </n-text>
          <n-text style="display: block; margin-bottom: 8px" data-testid="notifications-score-deadline">
            录分截止时间:{{ scoreDeadline ? fmtTime(scoreDeadline) : '未设置' }}
            · 未录完 {{ unsubmitted.unsubmittedClasses }} 个班级、{{ unsubmitted.unsubmittedStudents }} 人
          </n-text>
          <n-button
            v-if="canManage" type="primary" :loading="sending === 'score-deadline'"
            data-testid="notifications-send-score-deadline"
            @click="sendOne('score-deadline', () => notifyScoreDeadline(examId), '录分截止提醒')"
          >发送催录提醒</n-button>
          <n-text v-if="resultText('score-deadline')" style="display: block; margin-top: 8px" data-testid="notifications-result-score-deadline">
            {{ resultText('score-deadline') }}
          </n-text>
        </div></div>
      </div>

      <!-- 通知记录(KW-61) -->
      <div class="ios-section">
        <div class="ios-section-title">通知记录</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-alert type="info" style="margin-bottom: 12px" data-testid="notifications-health-hint">
            考务通知的聚合数据已进系统提醒健康页,可在系统设置里查看全校提醒健康状态。
            <n-button text type="primary" @click="goHealth">去系统提醒健康页</n-button>
          </n-alert>
          <n-space :wrap="true" align="center">
            <n-select
              v-model:value="filterType" :options="typeOptions" clearable
              placeholder="通知类型" style="width: 140px" @update:value="reloadLogs"
            />
            <n-select
              v-model:value="filterStatus" :options="statusOptions" clearable
              placeholder="发送状态" style="width: 120px" @update:value="reloadLogs"
            />
            <n-input
              v-model:value="filterQ" placeholder="按收件人检索" clearable
              style="width: 180px" @change="reloadLogs"
            />
            <n-button type="primary" @click="reloadLogs">检索</n-button>
          </n-space>
          <n-empty v-if="!logsLoading && logs.length === 0" description="暂无通知记录" style="margin-top: 12px" />
          <div v-for="log in logs" :key="log.id" class="ios-row" :data-testid="`notification-log-${log.id}`">
            <div class="ios-row-main">
              <div class="ios-row-title">{{ log.notification_type }} · {{ log.recipient_name }} · {{ log.channel }}</div>
              <div class="ios-row-sub">
                {{ log.status }}{{ log.error ? ` · ${log.error}` : '' }} · {{ fmtTime(log.sent_at ?? log.created_at) }}
                {{ log.message ? ` · ${log.message}` : '' }}
              </div>
            </div>
            <n-button
              v-if="canManage && canResendNotification(log)" size="small" type="primary"
              :data-testid="`notification-resend-${log.id}`" @click="onResend(log)"
            >重发</n-button>
          </div>
          <n-text depth="3" style="font-size: 13px">共 {{ logTotal }} 条</n-text>
        </div></div>
      </div>
    </template>
  </div>
</template>
