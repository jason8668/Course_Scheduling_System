<script setup lang="ts">
import {
  NAlert, NButton, NCollapse, NCollapseItem, NDatePicker, NEmpty, NInput,
  NPopconfirm, NSpace, NSwitch, NSelect, NText, NTimePicker, useMessage,
} from 'naive-ui'
import { onMounted, ref, watch } from 'vue'
import { acknowledge, markRead, myNotifications } from '@/api/notifications'
import type { Notification } from '@/api/notifications'
import { cancelLeave, createLeave, listLeaveTypes, listLeaves } from '@/api/leaves'
import type { LeaveRequest } from '@/api/leaves'
import { getMyStats } from '@/api/substitutionStats'
import type { MonthlyReport } from '@/api/substitutionStats'
import { getReminderPreference, saveReminderPreference } from '@/api/teacherHome'
import type { ReminderPreference } from '@/api/teacherHome'
import DutyRosterSection from '@/components/scheduling/DutyRosterSection.vue'
import TeacherSwapSection from '@/components/scheduling/TeacherSwapSection.vue'

// 原「我的」页除本周课表外的全部功能,抽成一节组件挂到仪表板上。
// 本周课表不搬:仪表板已有一张更好的(TimetableGrid + 值日行 + 受影响节次),
// 再搬一张就是重复,故这里只搬通知、请假、代课、提醒设置、值日、调课。
// semesterId 由仪表板给(已发布学期),不再自己查学期列表——
// 纯教师帐号查不了学期列表,原来「我的」页就是在这里卡住的。
const props = defineProps<{ semesterId: number }>()
const message = useMessage()

const preference = ref<ReminderPreference | null>(null)
const notifications = ref<Notification[]>([])
const leaves = ref<LeaveRequest[]>([])
const leaveTypes = ref<Record<string, string>>({})
const stats = ref<MonthlyReport | null>(null)

const remindEnabled = ref(true)
const leadSelect = ref<string | number>('follow')
const remindPhone = ref('')
const savingPref = ref(false)

const leaveForm = ref({
  leaveType: '', startDate: null as number | null, endDate: null as number | null,
  startTime: null as number | null, endTime: null as number | null, reason: '',
})
const submittingLeave = ref(false)

function toDate(ts: number | null): string | null {
  if (ts === null) return null
  const d = new Date(ts)
  return `${d.getFullYear()}-${`${d.getMonth() + 1}`.padStart(2, '0')}-${`${d.getDate()}`.padStart(2, '0')}`
}
function toTime(ts: number | null): string | null {
  if (ts === null) return null
  const d = new Date(ts)
  return `${`${d.getHours()}`.padStart(2, '0')}:${`${d.getMinutes()}`.padStart(2, '0')}`
}

async function loadAll() {
  const sid = props.semesterId
  const [pref, notifs, myLeaves, types] = await Promise.all([
    getReminderPreference(sid).catch(() => null),
    myNotifications(sid).catch(() => ({ items: [], unread: 0 })),
    listLeaves(sid).catch(() => [] as LeaveRequest[]),
    listLeaveTypes().catch(() => ({} as Record<string, string>)),
  ])
  preference.value = pref
  if (pref) {
    remindEnabled.value = pref.reminder_enabled
    leadSelect.value = pref.reminder_lead_minutes ?? 'follow'
    remindPhone.value = pref.phone ?? ''
  }
  notifications.value = [...notifs.items].sort((a, b) =>
    (a.read_at ? 1 : 0) - (b.read_at ? 1 : 0))
  leaves.value = myLeaves
  leaveTypes.value = types
  const now = new Date()
  stats.value = await getMyStats(sid, now.getFullYear(), now.getMonth() + 1).catch(() => null)
}

async function submitLeave() {
  const start = toDate(leaveForm.value.startDate)
  const end = toDate(leaveForm.value.endDate)
  if (!leaveForm.value.leaveType || !start || !end) {
    message.warning('请先选假别与起讫日期')
    return
  }
  submittingLeave.value = true
  try {
    await createLeave(props.semesterId, {
      leave_type: leaveForm.value.leaveType,
      start_date: start,
      start_time: toTime(leaveForm.value.startTime),
      end_date: end,
      end_time: toTime(leaveForm.value.endTime),
      reason: leaveForm.value.reason || undefined,
    })
    message.success('请假已登记')
    leaveForm.value = {
      leaveType: '', startDate: null, endDate: null, startTime: null, endTime: null, reason: '',
    }
    leaves.value = await listLeaves(props.semesterId)
  } catch (e) {
    message.error((e as Error).message || '登记失败')
  } finally {
    submittingLeave.value = false
  }
}

async function onCancelLeave(id: number) {
  try {
    await cancelLeave(id)
    message.success('已销假')
    leaves.value = await listLeaves(props.semesterId)
  } catch (e) {
    message.error((e as Error).message || '销假失败')
  }
}

async function refreshNotifications() {
  const notifs = await myNotifications(props.semesterId)
  notifications.value = [...notifs.items].sort((a, b) =>
    (a.read_at ? 1 : 0) - (b.read_at ? 1 : 0))
}
async function onMarkRead(id: number) {
  try {
    await markRead(id)
    await refreshNotifications()
  } catch (e) {
    message.error((e as Error).message || '操作失败')
  }
}
async function onAcknowledge(id: number) {
  try {
    await acknowledge(id)
    await refreshNotifications()
  } catch (e) {
    message.error((e as Error).message || '操作失败')
  }
}

async function savePref() {
  if (!preference.value?.bound) return
  savingPref.value = true
  try {
    const lead = leadSelect.value === 'follow' ? null : Number(leadSelect.value)
    preference.value = await saveReminderPreference(props.semesterId, {
      reminder_enabled: remindEnabled.value,
      reminder_lead_minutes: lead,
      phone: remindPhone.value.trim() || null,
    })
    message.success('提醒设置已保存')
  } catch (e) {
    message.error((e as Error).message || '保存失败')
  } finally {
    savingPref.value = false
  }
}

onMounted(() => { void loadAll() })
watch(() => props.semesterId, () => { void loadAll() })
</script>

<template>
  <div data-testid="teacher-home-sections">
    <n-alert v-if="preference && !preference.bound" type="warning" title="尚未绑定教师档案" style="margin-top: 16px">
      系统里还没有把你的账号对应到教师档案，请联系管理员开通；课表与提醒需要绑定后才能显示。
    </n-alert>

    <section class="ios-section" style="animation-delay: 60ms">
      <div class="ios-section-title">
        <span>通知</span>
        <span v-if="notifications.filter((n) => !n.read_at).length" class="ios-chip-warn ios-chip">
          {{ notifications.filter((n) => !n.read_at).length }} 条未读
        </span>
      </div>
      <div class="ios-card">
        <n-empty v-if="!notifications.length" description="暂无通知" style="padding: 24px 0" />
        <template v-else>
          <div v-for="n in notifications" :key="n.id" class="ios-row">
            <span v-if="!n.read_at" class="ios-dot" />
            <div class="ios-row-main">
              <div style="display: flex; align-items: baseline; gap: 8px">
                <span class="ios-row-title">{{ n.title }}</span>
                <span class="ios-row-sub">{{ n.created_at?.slice(0, 16) }}</span>
              </div>
              <div class="ios-row-sub">
                {{ n.body }}
              </div>
              <n-space style="margin-top: 4px">
                <n-button v-if="!n.read_at" size="small" text type="primary" @click="onMarkRead(n.id)">
                  标为已读
                </n-button>
                <n-button v-if="!n.acknowledged_at" size="small" text type="primary" @click="onAcknowledge(n.id)">
                  确认收到
                </n-button>
                <span v-else class="ios-chip-green ios-chip">已确认</span>
              </n-space>
            </div>
          </div>
        </template>
      </div>
    </section>

    <section class="ios-section" style="animation-delay: 120ms">
      <div class="ios-section-title">
        <span>我的请假</span>
      </div>
      <div class="ios-card">
        <div class="ios-card-body">
          <n-space align="end" :wrap="true">
            <n-select
              v-model:value="leaveForm.leaveType" :options="Object.entries(leaveTypes).map(([v, l]) => ({ label: l, value: v }))"
              placeholder="假别" style="width: 140px"
            />
            <n-date-picker v-model:value="leaveForm.startDate" type="date" placeholder="开始日期" style="width: 160px" />
            <n-date-picker v-model:value="leaveForm.endDate" type="date" placeholder="结束日期" style="width: 160px" />
            <n-time-picker v-model:value="leaveForm.startTime" placeholder="开始时间(可空)" format="HH:mm" style="width: 140px" />
            <n-time-picker v-model:value="leaveForm.endTime" placeholder="结束时间(可空)" format="HH:mm" style="width: 140px" />
            <n-input v-model:value="leaveForm.reason" placeholder="事由(可空)" style="width: 200px" />
          </n-space>
          <n-button type="primary" round :loading="submittingLeave" style="margin-top: 12px" @click="submitLeave">
            登记请假
          </n-button>
        </div>
        <n-empty v-if="!leaves.length" description="暂无请假记录" style="padding: 12px 0 24px" />
        <template v-else>
          <div v-for="l in leaves" :key="l.id" class="ios-row">
            <div class="ios-row-main">
              <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap">
                <span class="ios-row-title">{{ l.leave_type_label }}</span>
                <span class="ios-row-sub">{{ l.start_date }} ~ {{ l.end_date }}</span>
                <span :class="l.status === 'registered' ? 'ios-chip' : 'ios-chip-gray ios-chip'">
                  {{ l.status === 'registered' ? '已登记' : '已销假' }}
                </span>
                <span class="ios-row-sub">影响 {{ l.affected_count }} 节 · 待处理 {{ l.pending_count }} 节</span>
                <n-popconfirm
                  v-if="l.status === 'registered'" @positive-click="onCancelLeave(l.id)"
                >
                  <template #trigger>
                    <n-button size="small" text type="primary">
                      销假
                    </n-button>
                  </template>
                  确认销假吗？已上过的节次不受影响，其余待处理节次会取消。
                </n-popconfirm>
              </div>
              <n-collapse v-if="l.affected_periods.length" style="margin-top: 4px">
                <n-collapse-item title="受影响节次" :name="l.id">
                  <n-space vertical size="small">
                    <n-text v-for="ap in l.affected_periods" :key="ap.id" depth="2" style="font-size: 13px">
                      {{ ap.date }} {{ ap.period_name }} · {{ ap.subject_name }} · {{ ap.class_names }}
                      {{ ap.handler_name ? `（${ap.handler_name}代课）` : ap.status === 'pending' ? '（待处理）' : '' }}
                    </n-text>
                  </n-space>
                </n-collapse-item>
              </n-collapse>
            </div>
          </div>
        </template>
      </div>
    </section>

    <section class="ios-section" style="animation-delay: 180ms">
      <div class="ios-section-title">
        <span>我的代课</span>
      </div>
      <div class="ios-card">
        <n-empty v-if="!stats" description="暂无本月代课统计" style="padding: 24px 0" />
        <template v-else>
          <div class="ios-card-body">
            <n-text style="font-size: 15px">
              本月我代别人：{{ stats.summaries[0]?.handled_count ?? 0 }} 节
              （计入课时 {{ stats.summaries[0]?.billable_count ?? 0 }} 节）
            </n-text>
            <div class="ios-row-sub" style="margin-top: 2px">
              被代课的情况在上方“我的请假”里看：每单的影响节次会显示代课人。
            </div>
          </div>
          <div v-for="(d, i) in stats.details" :key="i" class="ios-row">
            <span style="font-size: 13px">
              {{ d.date }} {{ d.period_name }} · {{ d.class_names }}《{{ d.subject_name }}》
              · 代 {{ d.absent_teacher_name }}老师的课
            </span>
          </div>
        </template>
      </div>
    </section>

    <DutyRosterSection :semester-id="semesterId" :admin="false" />

    <TeacherSwapSection :semester-id="semesterId" :admin="false" />

    <section class="ios-section" style="animation-delay: 240ms">
      <div class="ios-section-title">
        <span>提醒设置</span>
      </div>
      <div class="ios-card">
        <n-empty v-if="!preference" description="暂无提醒设置" style="padding: 24px 0" />
        <template v-else>
          <n-alert v-if="!preference.bound" type="warning" style="margin: 12px 16px 0">
            尚未绑定教师档案，提醒设置需要绑定后才能保存。
          </n-alert>
          <div class="ios-row">
            <span class="ios-row-main" style="font-size: 15px">上课提醒</span>
            <n-switch v-model:value="remindEnabled" :disabled="!preference.bound" />
          </div>
          <div class="ios-row">
            <span class="ios-row-main" style="font-size: 15px">提前</span>
            <n-select
              v-model:value="leadSelect" :disabled="!preference.bound || !remindEnabled"
              :options="[
                { label: `跟随学校设置（${preference.global_lead_minutes}分钟）`, value: 'follow' },
                { label: '5 分钟', value: 5 },
                { label: '10 分钟', value: 10 },
                { label: '15 分钟', value: 15 },
                { label: '30 分钟', value: 30 },
              ]" style="width: 220px"
            />
          </div>
          <div class="ios-row">
            <span class="ios-row-main" style="font-size: 15px">手机号</span>
            <n-input
              v-model:value="remindPhone" :disabled="!preference.bound" placeholder="钉钉通讯录里的手机号"
              style="width: 200px"
            />
            <span :class="preference.dingtalk_bound ? 'ios-chip-green ios-chip' : 'ios-chip-warn ios-chip'">
              {{ preference.dingtalk_bound ? '钉钉已绑定' : '钉钉未绑定' }}
            </span>
          </div>
          <div class="ios-card-body">
            <div class="ios-row-sub" style="margin-bottom: 8px">
              关了就不会收到上课提醒；手机号变了会重新匹配钉钉，改完下次提醒时生效。
            </div>
            <n-button type="primary" round :loading="savingPref" :disabled="!preference.bound" @click="savePref">
              保存提醒设置
            </n-button>
          </div>
        </template>
      </div>
    </section>

  </div>
</template>
