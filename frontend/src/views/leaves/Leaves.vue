<script setup lang="ts">
import {
  NAlert, NButton, NDatePicker, NEmpty, NInput, NPopconfirm, NSelect, NSpace, NSwitch,
  NTag, NText, NTimePicker, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import { listTeachers } from '@/api/basedata'
import { cancelLeave, createLeave, listLeaveTypes, listLeaves } from '@/api/leaves'
import type { AffectedPeriod, LeaveRequest } from '@/api/leaves'
import { listSemesters } from '@/api/semesters'
import { publishedSemesters } from '@/api/timetables'
import { useAuthStore } from '@/stores/auth'
import MySubstitutionSection from '@/components/teacher/MySubstitutionSection.vue'
import TeacherSwapSection from '@/components/scheduling/TeacherSwapSection.vue'

const auth = useAuthStore()
const message = useMessage()

// 组长/主任可代登、可看全校;教师只登记自己的假、只看自己的假单
const canManage = computed(() =>
  auth.hasRole('admin') || auth.hasRole('director'))

const semesters = ref<{ id: number; label: string }[]>([])
const sid = ref<number | null>(null)
const leaveTypes = ref<Record<string, string>>({})
const teachers = ref<{ id: number; name: string }[]>([])
const leaves = ref<LeaveRequest[]>([])
const saving = ref(false)

// 后端的保护性上限(leaves.MAX_LEAVE_ROWS)。刚好取到上限笔数,几乎必然是被截断了。
const MAX_LEAVE_ROWS = 1000
const truncated = computed(() => leaves.value.length >= MAX_LEAVE_ROWS)

const form = ref({
  teacherId: null as number | null,
  leaveType: 'sick',
  // NDatePicker 给的是 timestamp,送出前才转成 YYYY-MM-DD
  startDate: null as number | null,
  endDate: null as number | null,
  halfDay: false,
  startTime: null as number | null,
  endTime: null as number | null,
  reason: '',
})

const semesterOptions = computed(() => semesters.value.map((s) => ({ label: s.label, value: s.id })))
const teacherOptions = computed(() => teachers.value.map((t) => ({ label: t.name, value: t.id })))
const typeOptions = computed(() =>
  Object.entries(leaveTypes.value).map(([value, label]) => ({ label, value })))

/** 本机日期,不用 toISOString——那会转成 UTC,台湾时区的凌晨会倒退一天。 */
function toDate(ts: number | null): string | null {
  if (ts === null) return null
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
function toTime(ts: number | null): string | null {
  if (ts === null) return null
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function reload() {
  if (!sid.value) return
  leaves.value = await listLeaves(sid.value)
  if (canManage.value) {
    teachers.value = await listTeachers(sid.value)
  }
}

async function onSemesterChange(id: number) {
  sid.value = id
  await reload()
}

onMounted(async () => {
  leaveTypes.value = await listLeaveTypes()
  semesters.value = canManage.value ? await listSemesters() : await publishedSemesters()
  if (semesters.value.length) await onSemesterChange(semesters.value[0].id)
})

const canSubmit = computed(() =>
  !!sid.value && !!form.value.startDate && !!form.value.endDate
  && (!canManage.value || !!form.value.teacherId))

async function onSubmit() {
  if (!sid.value || !canSubmit.value) return
  saving.value = true
  try {
    const created = await createLeave(sid.value, {
      teacher_id: canManage.value ? form.value.teacherId : null,
      leave_type: form.value.leaveType,
      start_date: toDate(form.value.startDate)!,
      end_date: toDate(form.value.endDate)!,
      start_time: form.value.halfDay ? toTime(form.value.startTime) : null,
      end_time: form.value.halfDay ? toTime(form.value.endTime) : null,
      reason: form.value.reason,
    })
    message.success(
      created.affected_count
        ? `已登记,共 ${created.affected_count} 节课受影响`
        : '已登记(这段期间没有课)',
    )
    form.value.reason = ''
    await reload()
  } catch (e) {
    message.error((e as ApiError).message || '登记失败')
  } finally {
    saving.value = false
  }
}

async function onCancel(leave: LeaveRequest) {
  const result = await cancelLeave(leave.id)
  if (result.notified_teachers.length) {
    message.success(`已销假,已通知 ${result.notified_teachers.join('、')} 取消代课`)
  } else {
    message.success('已销假')
  }
  await reload()
}

// 已取消不该和「待处理」一样抢眼——组长扫过这张表时,要一眼看出还有几节没人处理。
// (Naive 的 type="default" 在此情境仍沿用前一次的主题色,索性不用 tag。)
const STATUS_TAG: Record<AffectedPeriod['status'], { type: string; label: string }> = {
  pending: { type: 'warning', label: '待处理' },
  resolved: { type: 'info', label: '已确认' },
  completed: { type: 'success', label: '已完成' },
  cancelled: { type: 'default', label: '已取消' },
}

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

/** 「2026-11-11(周三)」——没有星期,教学组长无从一眼看出为什么跨了六天却只有一天有课。 */
function withWeekday(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return `${iso}(${WEEKDAYS[new Date(y, m - 1, d).getDay()]})`
}

function rangeText(l: LeaveRequest): string {
  if (l.start_date !== l.end_date) {
    return `${withWeekday(l.start_date)} ~ ${withWeekday(l.end_date)}`
  }
  if (l.start_time || l.end_time) {
    const from = l.start_time?.slice(0, 5) ?? '上课起'
    const to = l.end_time?.slice(0, 5) ?? '放学'
    return `${withWeekday(l.start_date)} ${from}~${to}`
  }
  return `${withWeekday(l.start_date)} 整天`
}
</script>

<template>
  <div class="ios-page">
    <n-space align="center">
      <h1 class="ios-title">调课管理</h1>
      <n-select
        :value="sid" :options="semesterOptions" style="width: 220px"
        placeholder="选择学期" @update:value="onSemesterChange"
      />
    </n-space>

    <n-empty v-if="!sid" description="尚无可登记请假的学期" />

    <template v-else>
      <section class="ios-section">
        <div class="ios-section-title">{{ canManage ? '登记请假(可代教师登记)' : '登记我的请假' }}</div>
        <div class="ios-card">
          <div class="ios-card-body">
        <n-space vertical>
          <n-space align="center" :wrap="true">
            <template v-if="canManage">
              <n-text>教师</n-text>
              <n-select
                v-model:value="form.teacherId" :options="teacherOptions" filterable
                style="width: 160px" placeholder="选择教师" data-testid="lv-teacher"
              />
            </template>
            <n-text>假别</n-text>
            <n-select
              v-model:value="form.leaveType" :options="typeOptions"
              style="width: 120px" data-testid="lv-type"
            />
            <n-text>起</n-text>
            <n-date-picker v-model:value="form.startDate" type="date" data-testid="lv-start" />
            <n-text>讫</n-text>
            <n-date-picker v-model:value="form.endDate" type="date" data-testid="lv-end" />
          </n-space>

          <n-space align="center">
            <n-switch v-model:value="form.halfDay" data-testid="lv-halfday" />
            <n-text>指定时间(半天假)</n-text>
            <template v-if="form.halfDay">
              <n-time-picker
                v-model:value="form.startTime" format="HH:mm" data-testid="lv-start-time"
              />
              <n-text>~</n-text>
              <n-time-picker
                v-model:value="form.endTime" format="HH:mm" data-testid="lv-end-time"
              />
            </template>
          </n-space>

          <n-input
            v-model:value="form.reason" placeholder="事由(选填)" maxlength="200"
            data-testid="lv-reason"
          />
          <n-text depth="3">
            受影响节次依「已发布课表」自动展开;周末与没有课的日子不会列入。
          </n-text>
          <div>
            <n-button
              type="primary" :loading="saving" :disabled="!canSubmit"
              data-testid="lv-submit" @click="onSubmit"
            >
              登记请假
            </n-button>
          </div>
        </n-space>
          </div>
        </div>
      </section>

      <n-alert v-if="truncated" type="warning" :bordered="false" data-testid="lv-truncated">
        只显示最新的 {{ MAX_LEAVE_ROWS }} 张假单,更早的未列出;要查更早的请到「调代课纪录」以日期区间查询。
      </n-alert>

      <n-empty v-if="!leaves.length" description="尚无请假纪录" />
      <section
        v-for="l in leaves" :key="l.id" class="ios-section" data-testid="lv-card"
      >
        <div class="ios-section-title">
          <span>{{ `${l.teacher_name} · ${l.leave_type_label} · ${rangeText(l)}` }}</span>
          <span>
            <n-space align="center">
              <n-tag v-if="l.status === 'cancelled'" type="default" size="small">已销假</n-tag>
              <n-tag v-else type="warning" size="small" data-testid="lv-pending">
                待处理 {{ l.pending_count }} 节
              </n-tag>
              <n-popconfirm v-if="l.status === 'registered'" @positive-click="onCancel(l)">
                <template #trigger>
                  <n-button size="small" tertiary type="error" data-testid="lv-cancel">销假</n-button>
                </template>
                销假将取消所有受影响节次的处置,已被指派的代课教师会收到取消通知。确定?
              </n-popconfirm>
            </n-space>
          </span>
        </div>
        <div class="ios-card">
          <div class="ios-card-body">

        <n-space vertical size="small">
          <n-text v-if="l.reason" depth="3">事由:{{ l.reason }}</n-text>
          <n-alert v-if="!l.affected_count" type="info" :bordered="false">
            这段期间没有课(周末,或课表尚未发布)
          </n-alert>
          <table v-else class="ios-table" data-testid="lv-affected">
            <thead>
              <tr><th>日期</th><th>节次</th><th>班级</th><th>科目</th><th>场地</th><th>状态</th></tr>
            </thead>
            <tbody>
              <tr v-for="p in l.affected_periods" :key="p.id">
                <td>{{ withWeekday(p.date) }}</td>
                <td>{{ p.period_name }}</td>
                <td>{{ p.class_names }}</td>
                <td>{{ p.subject_name }}</td>
                <td>{{ p.room_name || '—' }}</td>
                <td>
                  <n-text v-if="p.status === 'cancelled'" depth="3" data-testid="lv-status">
                    已取消
                  </n-text>
                  <n-tag
                    v-else size="small" data-testid="lv-status"
                    :type="STATUS_TAG[p.status].type as never"
                  >
                    {{ STATUS_TAG[p.status].label }}
                  </n-tag>
                  <n-text v-if="p.handler_name" depth="3"> · {{ p.handler_name }}</n-text>
                </td>
              </tr>
            </tbody>
          </table>
          <n-text depth="3">登记人:{{ l.created_by_name }}</n-text>
        </n-space>
          </div>
        </div>
      </section>

      <!-- 2026-10-30 Jason 定:仪表板上的我的代课与老师调课搬到这里,
        本页改名调课管理(请假 + 代课 + 调课都在这一页办)。
        我的代课只给教师本人看;老师调课:教师发起/确认自己的,管理员只看全部不批。 -->
      <MySubstitutionSection v-if="!canManage" :semester-id="sid" />
      <TeacherSwapSection :semester-id="sid" :admin="canManage" />
    </template>
  </div>
</template>
