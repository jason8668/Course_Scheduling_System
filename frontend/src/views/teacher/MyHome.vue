<script setup lang="ts">
import {
  NAlert, NButton, NCard, NCollapse, NCollapseItem, NDatePicker, NEmpty, NInput, NList, NListItem,
  NPopconfirm, NSelect, NSpace, NSwitch, NTag, NText, NTimePicker, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { listSemesters } from '@/api/semesters'
import type { SemesterListItem } from '@/api/semesters'
import { getMyTeacher, getPublishedTimetable, publishedSemesters } from '@/api/timetables'
import type { NamedBrief, PublishedTimetable, ScheduleEntry } from '@/api/timetables'
import { acknowledge, markRead, myNotifications } from '@/api/notifications'
import type { Notification } from '@/api/notifications'
import { cancelLeave, createLeave, listLeaveTypes, listLeaves } from '@/api/leaves'
import type { LeaveRequest } from '@/api/leaves'
import { getMyStats } from '@/api/substitutionStats'
import type { MonthlyReport } from '@/api/substitutionStats'
import { getReminderPreference, saveReminderPreference } from '@/api/teacherHome'
import type { ReminderPreference } from '@/api/teacherHome'

const message = useMessage()
const loading = ref(true)
const semester = ref<SemesterListItem | null>(null)
const weekData = ref<PublishedTimetable | null>(null)
const me = ref<NamedBrief | null>(null)
const preference = ref<ReminderPreference | null>(null)
const notifications = ref<Notification[]>([])
const leaves = ref<LeaveRequest[]>([])
const leaveTypes = ref<Record<string, string>>({})
const stats = ref<MonthlyReport | null>(null)

// ── 提醒设置表单(与后端自配置一一对应;select 用 'follow' 表示跟随学校设置) ──
const remindEnabled = ref(true)
const leadSelect = ref<string | number>('follow')
const remindPhone = ref('')
const savingPref = ref(false)

// ── 请假表单(教师自登:不指定 teacher_id,走 Leaves.vue 同款流程) ──
const leaveForm = ref({
  leaveType: '', startDate: null as number | null, endDate: null as number | null,
  startTime: null as number | null, endTime: null as number | null, reason: '',
})
const submittingLeave = ref(false)

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']
const todayIso = computed(() => ((new Date().getDay() + 6) % 7) + 1)

const myEntries = computed<ScheduleEntry[]>(() => {
  if (!weekData.value || !me.value) return []
  return weekData.value.entries.filter((e) => e.teacher_ids.includes(me.value!.id))
})
const gridWeekdays = computed(() => {
  const set = new Set(myEntries.value.map((e) => e.weekday))
  const days = [1, 2, 3, 4, 5].filter((d) => set.has(d))
  for (const d of [6, 7]) if (set.has(d)) days.push(d)
  return days
})
const gridPeriods = computed(() => [...new Set(myEntries.value.map((e) => e.period_no))].sort((a, b) => a - b))

function periodLabel(weekday: number, periodNo: number): string {
  const tables = weekData.value?.period_tables ?? []
  for (const t of tables) {
    const cell = t.periods.find((p) => p.weekday === weekday && p.period_no === periodNo)
    if (cell) return `${cell.name}${cell.start_time ? ` ${cell.start_time.slice(0, 5)}` : ''}`
  }
  return `第${periodNo}节`
}
function cellEntries(weekday: number, periodNo: number): ScheduleEntry[] {
  return myEntries.value.filter((e) => e.weekday === weekday && e.period_no === periodNo)
}
function parityLabel(p: 'odd' | 'even' | null | undefined): string | null {
  if (p === 'odd') return '单周'
  if (p === 'even') return '双周'
  return null
}

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
  loading.value = true
  try {
    const semesters = await listSemesters()
    if (!semesters.length) return
    semester.value = semesters[0]
    const sid = semesters[0].id
    const [pubs, myTeacher, pref, notifs, myLeaves, types] = await Promise.all([
      publishedSemesters().catch(() => []),
      getMyTeacher(sid).catch(() => null),
      getReminderPreference(sid).catch(() => null),
      myNotifications(sid).catch(() => ({ items: [], unread: 0 })),
      listLeaves(sid).catch(() => [] as LeaveRequest[]),
      listLeaveTypes().catch(() => ({} as Record<string, string>)),
    ])
    me.value = myTeacher
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
    if (pubs.length) {
      weekData.value = await getPublishedTimetable(pubs[0].id).catch(() => null)
    }
    const now = new Date()
    stats.value = await getMyStats(sid, now.getFullYear(), now.getMonth() + 1).catch(() => null)
  } finally {
    loading.value = false
  }
}

async function submitLeave() {
  if (!semester.value) return
  const start = toDate(leaveForm.value.startDate)
  const end = toDate(leaveForm.value.endDate)
  if (!leaveForm.value.leaveType || !start || !end) {
    message.warning('请先选假别与起讫日期')
    return
  }
  submittingLeave.value = true
  try {
    await createLeave(semester.value.id, {
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
    leaves.value = await listLeaves(semester.value.id)
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
    if (semester.value) leaves.value = await listLeaves(semester.value.id)
  } catch (e) {
    message.error((e as Error).message || '销假失败')
  }
}

async function onMarkRead(id: number) {
  try {
    await markRead(id)
    if (semester.value) {
      const notifs = await myNotifications(semester.value.id)
      notifications.value = [...notifs.items].sort((a, b) =>
        (a.read_at ? 1 : 0) - (b.read_at ? 1 : 0))
    }
  } catch (e) {
    message.error((e as Error).message || '操作失败')
  }
}

async function onAcknowledge(id: number) {
  try {
    await acknowledge(id)
    if (semester.value) {
      const notifs = await myNotifications(semester.value.id)
      notifications.value = [...notifs.items].sort((a, b) =>
        (a.read_at ? 1 : 0) - (b.read_at ? 1 : 0))
    }
  } catch (e) {
    message.error((e as Error).message || '操作失败')
  }
}

async function savePref() {
  if (!semester.value || !preference.value?.bound) return
  savingPref.value = true
  try {
    const lead = leadSelect.value === 'follow' ? null : Number(leadSelect.value)
    preference.value = await saveReminderPreference(semester.value.id, {
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
</script>

<template>
  <n-space vertical size="medium" class="my-home" style="max-width: 960px">
    <h1 style="margin: 0">
      我的
    </h1>
    <n-alert v-if="preference && !preference.bound" type="warning" title="尚未绑定教师档案">
      系统里还没有把你的账号对应到教师档案，请联系管理员开通；课表与提醒需要绑定后才能显示。
    </n-alert>
    <n-alert v-if="!semester && !loading" type="info" title="暂无学期">
      还没有建立学期，请联系管理员。
    </n-alert>

    <n-card title="本周我的课表" :loading="loading">
      <n-empty v-if="!weekData || !me" description="暂无已发布课表或尚未绑定教师档案" />
      <table v-else style="width: 100%; border-collapse: collapse">
        <thead>
          <tr>
            <th style="text-align: left; padding: 4px 6px; border-bottom: 1px solid #eee">
              节次
            </th>
            <th
              v-for="d in gridWeekdays" :key="d"
              style="text-align: left; padding: 4px 6px; border-bottom: 1px solid #eee"
            >
              周{{ WEEKDAYS[d - 1] }}
              <n-tag v-if="d === todayIso" type="primary" size="small" style="margin-left: 4px">
                今天
              </n-tag>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in gridPeriods" :key="p">
            <td style="padding: 4px 6px; border-bottom: 1px solid #f5f5f5; white-space: nowrap">
              {{ periodLabel(gridWeekdays[0] ?? 1, p) }}
            </td>
            <td
              v-for="d in gridWeekdays" :key="d"
              style="padding: 4px 6px; border-bottom: 1px solid #f5f5f5; vertical-align: top"
            >
              <div v-for="e in cellEntries(d, p)" :key="e.id" style="margin-bottom: 2px">
                <n-text strong>
                  {{ e.subject }}
                </n-text>
                <n-text depth="3" style="margin-left: 6px">
                  {{ e.classes.join('、') }}{{ e.room ? ` · ${e.room}` : '' }}
                </n-text>
                <n-tag
                  v-if="parityLabel(e.week_parity)" size="small" style="margin-left: 4px"
                >
                  {{ parityLabel(e.week_parity) }}
                </n-tag>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </n-card>

    <n-card title="通知" :loading="loading">
      <n-empty v-if="!notifications.length" description="暂无通知" />
      <n-list v-else>
        <n-list-item v-for="n in notifications" :key="n.id">
          <n-space vertical size="small" style="width: 100%">
            <n-space align="center">
              <n-tag v-if="!n.read_at" type="warning" size="small">
                未读
              </n-tag>
              <n-text strong>
                {{ n.title }}
              </n-text>
              <n-text depth="3" style="font-size: 12px">
                {{ n.created_at?.slice(0, 16) }}
              </n-text>
            </n-space>
            <n-text depth="2">
              {{ n.body }}
            </n-text>
            <n-space>
              <n-button v-if="!n.read_at" size="small" @click="onMarkRead(n.id)">
                标为已读
              </n-button>
              <n-button v-if="!n.acknowledged_at" size="small" type="primary" @click="onAcknowledge(n.id)">
                确认收到
              </n-button>
              <n-tag v-else size="small" type="success">
                已确认
              </n-tag>
            </n-space>
          </n-space>
        </n-list-item>
      </n-list>
    </n-card>

    <n-card title="我的请假" :loading="loading">
      <n-space vertical>
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
          <n-button type="primary" :loading="submittingLeave" @click="submitLeave">
            登记请假
          </n-button>
        </n-space>
        <n-empty v-if="!leaves.length" description="暂无请假记录" />
        <n-list v-else>
          <n-list-item v-for="l in leaves" :key="l.id">
            <n-space vertical size="small" style="width: 100%">
              <n-space align="center" :wrap="true">
                <n-text strong>
                  {{ l.leave_type_label }}
                </n-text>
                <n-text>{{ l.start_date }} ~ {{ l.end_date }}</n-text>
                <n-tag :type="l.status === 'registered' ? 'info' : 'default'" size="small">
                  {{ l.status === 'registered' ? '已登记' : '已销假' }}
                </n-tag>
                <n-text depth="3" style="font-size: 12px">
                  影响 {{ l.affected_count }} 节 · 待处理 {{ l.pending_count }} 节
                </n-text>
                <n-popconfirm
                  v-if="l.status === 'registered'" @positive-click="onCancelLeave(l.id)"
                >
                  <template #trigger>
                    <n-button size="small">
                      销假
                    </n-button>
                  </template>
                  确认销假吗？已上过的节次不受影响，其余待处理节次会取消。
                </n-popconfirm>
              </n-space>
              <n-collapse v-if="l.affected_periods.length">
                <n-collapse-item title="受影响节次" :name="l.id">
                  <n-space vertical size="small">
                    <n-text v-for="ap in l.affected_periods" :key="ap.id" depth="2" style="font-size: 13px">
                      {{ ap.date }} {{ ap.period_name }} · {{ ap.subject_name }} · {{ ap.class_names }}
                      {{ ap.handler_name ? `（${ap.handler_name}代课）` : ap.status === 'pending' ? '（待处理）' : '' }}
                    </n-text>
                  </n-space>
                </n-collapse-item>
              </n-collapse>
            </n-space>
          </n-list-item>
        </n-list>
      </n-space>
    </n-card>

    <n-card title="我的代课" :loading="loading">
      <n-empty v-if="!stats" description="暂无本月代课统计" />
      <n-space v-else vertical>
        <n-text>
          本月我代别人：{{ stats.summaries[0]?.handled_count ?? 0 }} 节
          （计入课时 {{ stats.summaries[0]?.billable_count ?? 0 }} 节）
        </n-text>
        <n-text depth="3" style="font-size: 13px">
          被代课的情况在上方“我的请假”里看：每单的影响节次会显示代课人。
        </n-text>
        <n-list v-if="stats.details.length">
          <n-list-item v-for="(d, i) in stats.details" :key="i">
            <n-text style="font-size: 13px">
              {{ d.date }} {{ d.period_name }} · {{ d.class_names }}《{{ d.subject_name }}》
              · 代 {{ d.absent_teacher_name }}老师的课
            </n-text>
          </n-list-item>
        </n-list>
      </n-space>
    </n-card>

    <n-card title="提醒设置" :loading="loading">
      <n-empty v-if="!preference" description="暂无提醒设置" />
      <n-space v-else vertical>
        <n-alert v-if="!preference.bound" type="warning">
          尚未绑定教师档案，提醒设置需要绑定后才能保存。
        </n-alert>
        <n-space align="center">
          <n-text>上课提醒</n-text>
          <n-switch v-model:value="remindEnabled" :disabled="!preference.bound" />
          <n-text depth="3" style="font-size: 13px">
            {{ remindEnabled ? '开' : '关' }}（关了就不会收到上课提醒）
          </n-text>
        </n-space>
        <n-space align="center" :wrap="true">
          <n-text>提前</n-text>
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
          <n-text depth="3" style="font-size: 13px">
            每节课前推到你的个人钉钉
          </n-text>
        </n-space>
        <n-space align="center" :wrap="true">
          <n-text>手机号</n-text>
          <n-input
            v-model:value="remindPhone" :disabled="!preference.bound" placeholder="钉钉通讯录里的手机号"
            style="width: 200px"
          />
          <n-tag :type="preference.dingtalk_bound ? 'success' : 'warning'" size="small">
            {{ preference.dingtalk_bound ? '钉钉已绑定' : '钉钉未绑定' }}
          </n-tag>
          <n-text depth="3" style="font-size: 13px">
            手机号变了会重新匹配钉钉，改完下次提醒时生效
          </n-text>
        </n-space>
        <n-button type="primary" :loading="savingPref" :disabled="!preference.bound" @click="savePref">
          保存提醒设置
        </n-button>
      </n-space>
    </n-card>
  </n-space>
</template>

<style scoped>
/* 精简排版:卡片与列表收紧,页面不摊太宽 */
.my-home :deep(.n-card-header) {
  padding: 10px 16px 6px;
}
.my-home :deep(.n-card-header__title) {
  font-size: 15px;
}
.my-home :deep(.n-card__content) {
  padding: 12px 16px;
}
.my-home :deep(.n-list-item) {
  padding-top: 8px;
  padding-bottom: 8px;
}
</style>
