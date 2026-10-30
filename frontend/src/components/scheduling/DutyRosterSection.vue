/**
 * 行政值日(全校共用一位,不算课时,当天照常上课)。
 * 管理员模式(admin=true):排每周轮值、改某天覆盖(请假替班也在这里改)、看全部换班申请。
 * 教师模式(admin=false):看自己的值日与换班申请,为自己值日的那天发起换班,
 * 对方老师在申请上点同意后当天值日就换过去(只换当天,下周恢复轮值)。
 * 轮值人选只有行政岗位老师,下拉只列这些人。
 */
<script setup lang="ts">
import {
  NAlert, NButton, NDatePicker, NEmpty, NInput, NPopconfirm, NSelect, NSpace, NText,
  useMessage,
} from 'naive-ui'
import { computed, ref, watch } from 'vue'
import type { ApiError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { listSemesters } from '@/api/semesters'
import {
  WEEKDAY_LABELS, approveDutySwap, createDutySwapRequest, deleteDutyOverride,
  getDutyRoster, rejectDutySwap, setDutyOverride, setDutyPattern,
} from '@/api/duty'
import type { DutyRoster } from '@/api/duty'

const props = defineProps<{ semesterId?: number | null; admin: boolean; teacherId?: number | null }>()
const message = useMessage()
const auth = useAuthStore()

// 值日只给行政岗位显示(Jason 2026-10-30 定):普通老师没有这个模块。
// 判断:管理员模式一律显示;教师模式下,本人是轮值人选(行政岗位,roster.eligible 里有他)
// 或帐号本身是管理员/主任,才显示;否则等 roster 载入后整个节隐藏。
// roster 未载入前先不画,避免先闪一下再消失。
const showSection = computed(() => {
  if (props.admin) return true
  if (auth.hasRole('admin') || auth.hasRole('director')) return true
  if (roster.value === null) return false
  if (props.teacherId === null || props.teacherId === undefined) return true
  return roster.value.eligible.some((t) => t.id === props.teacherId)
})

const roster = ref<DutyRoster | null>(null)
const loading = ref(false)
// 没有传学期时(如系统管理页),组件自己选学期
const semesters = ref<{ id: number; label: string }[]>([])
const selectedSemesterId = ref<number | null>(props.semesterId ?? null)
const effectiveSemesterId = computed(() => props.semesterId ?? selectedSemesterId.value)

function localDate(ts: number | null): string | null {
  if (ts === null) return null
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

const eligibleOptions = computed(() =>
  (roster.value?.eligible ?? []).map((t) => ({
    label: t.admin_title ? `${t.name}(${t.admin_title})` : t.name,
    value: t.id,
  })),
)
const patternTeacher = (weekday: number) =>
  roster.value?.patterns.find((p) => p.weekday === weekday)?.teacher_id ?? null

async function load() {
  const sid = effectiveSemesterId.value
  if (sid === null || sid === undefined) {
    roster.value = null
    return
  }
  loading.value = true
  try {
    roster.value = await getDutyRoster(sid)
  } catch (e) {
    message.error((e as ApiError).detail ?? '载入值日失败')
  } finally {
    loading.value = false
  }
}
watch(effectiveSemesterId, load, { immediate: true })
if (props.semesterId === null || props.semesterId === undefined) {
  listSemesters().then((list) => {
    semesters.value = list
    if (list.length && selectedSemesterId.value === null) selectedSemesterId.value = list[0].id
  }).catch(() => { /* 无学期时组件显示请先选择学期 */ })
}
watch(() => props.semesterId, (v) => { selectedSemesterId.value = v ?? null })

async function onPattern(weekday: number, teacherId: number | null) {
  if (effectiveSemesterId.value === null || teacherId === null) return
  try {
    roster.value = await setDutyPattern(effectiveSemesterId.value!, weekday, teacherId)
    message.success(`${WEEKDAY_LABELS[weekday]}值日已排好,每周重复`)
  } catch (e) {
    message.error((e as ApiError).detail ?? '排轮值失败')
  }
}

const overrideDateTs = ref<number | null>(null)
const overrideTeacher = ref<number | null>(null)
const overrideReason = ref('')
async function onOverride() {
  if (effectiveSemesterId.value === null) return
  const dateStr = localDate(overrideDateTs.value)
  if (!dateStr || overrideTeacher.value === null) {
    message.warning('请先选日期与替班/值日老师')
    return
  }
  try {
    roster.value = await setDutyOverride(
      effectiveSemesterId.value!, dateStr, overrideTeacher.value, overrideReason.value.trim() || null,
    )
    message.success(`${dateStr}的值日已改好,只影响当天,下周恢复轮值`)
  } catch (e) {
    message.error((e as ApiError).detail ?? '改覆盖失败')
  }
}
async function onDeleteOverride(dateStr: string) {
  if (effectiveSemesterId.value === null) return
  try {
    await deleteDutyOverride(effectiveSemesterId.value!, dateStr)
    message.success('已取消当天覆盖,恢复轮值')
    await load()
  } catch (e) {
    message.error((e as ApiError).detail ?? '取消失败')
  }
}

const swapDateTs = ref<number | null>(null)
const swapTo = ref<number | null>(null)
async function onSwapRequest() {
  if (effectiveSemesterId.value === null) return
  const dateStr = localDate(swapDateTs.value)
  if (!dateStr || swapTo.value === null) {
    message.warning('请先选要换班的日期与对方老师')
    return
  }
  try {
    await createDutySwapRequest(effectiveSemesterId.value!, dateStr, swapTo.value)
    message.success('换班申请已发给对方老师,对方同意后当天值日就换过去')
    await load()
  } catch (e) {
    message.error((e as ApiError).detail ?? '发起换班失败')
  }
}
async function onApprove(id: number) {
  try {
    await approveDutySwap(id)
    message.success('已同意,当天值日已换成你')
    await load()
  } catch (e) {
    message.error((e as ApiError).detail ?? '同意失败(只有被换班的老师能同意)')
  }
}
async function onReject(id: number) {
  try {
    await rejectDutySwap(id)
    message.success('已拒绝')
    await load()
  } catch (e) {
    message.error((e as ApiError).detail ?? '拒绝失败')
  }
}
</script>

<template>
  <section v-if="showSection" class="ios-section" data-testid="duty-section">
    <div class="ios-section-title">
      <span>行政值日</span>
      <span class="ios-row-sub">全校共用一位,不算课时,当天照常上课</span>
    </div>
    <div class="ios-card">
      <div class="ios-card-body">
        <n-space v-if="semesterId === null || semesterId === undefined" align="center">
          <n-text>选择学期</n-text>
          <n-select
            v-model:value="selectedSemesterId" :options="semesters.map((s) => ({ label: s.label, value: s.id }))"
            placeholder="选择学期" style="width: 220px" data-testid="duty-semester"
          />
        </n-space>
        <n-alert v-if="effectiveSemesterId === null || effectiveSemesterId === undefined" type="info">
          请先选择学期。
        </n-alert>
        <template v-else-if="roster">
          <div v-if="admin">
            <n-text strong>每周轮值(手动排,每周重复)</n-text>
            <div class="ios-row-sub">轮值人选只有行政岗位老师;排好后每周自动重复,不用每周重排。</div>
            <n-space vertical size="small" style="margin-top: 8px">
              <n-space v-for="w in [1, 2, 3, 4, 5, 6, 7]" :key="w" align="center">
                <n-text style="width: 48px">{{ WEEKDAY_LABELS[w] }}</n-text>
                <n-select
                  :value="patternTeacher(w)" :options="eligibleOptions" placeholder="未排"
                  style="width: 220px" :data-testid="`duty-pattern-${w}`"
                  @update:value="(v: number) => onPattern(w, v)"
                />
              </n-space>
            </n-space>

            <n-text strong style="display: block; margin-top: 16px">某天临时改(只影响当天)</n-text>
            <div class="ios-row-sub">值日老师请假要指定替班、或临时调整,都在这里改某天:下周恢复轮值。</div>
            <n-space align="center" :wrap="true" style="margin-top: 8px">
              <n-date-picker v-model:value="overrideDateTs" type="date" placeholder="哪一天" style="width: 150px" data-testid="duty-override-date" />
              <n-select v-model:value="overrideTeacher" :options="eligibleOptions" placeholder="改成谁" style="width: 200px" data-testid="duty-override-teacher" />
              <n-input v-model:value="overrideReason" placeholder="原因(选填,例如请假替班)" style="width: 200px" data-testid="duty-override-reason" />
              <n-button type="primary" round data-testid="duty-override-save" @click="onOverride">
                改当天
              </n-button>
            </n-space>
            <n-space v-if="roster.overrides.length" vertical size="small" style="margin-top: 8px">
              <n-space v-for="o in roster.overrides" :key="o.id" align="center">
                <n-text>{{ o.date }} → {{ o.teacher_name }}{{ o.reason ? `(${o.reason})` : '' }}</n-text>
                <n-popconfirm @positive-click="onDeleteOverride(o.date)">
                  <template #trigger>
                    <n-button size="small" text type="error">取消覆盖</n-button>
                  </template>
                  取消后当天恢复轮值,确定?
                </n-popconfirm>
              </n-space>
            </n-space>
          </div>

          <div style="margin-top: 16px">
            <n-text strong>换班申请</n-text>
            <div class="ios-row-sub">
              老师为自己值日的那天发起换班,对方同意后当天值日就换过去(只换当天)。
              管理员要直接改请用上面的轮值/临时改,不走申请。
            </div>
            <n-space v-if="!admin" align="center" :wrap="true" style="margin-top: 8px">
              <n-date-picker v-model:value="swapDateTs" type="date" placeholder="要换哪天" style="width: 150px" data-testid="duty-swap-date" />
              <n-select v-model:value="swapTo" :options="eligibleOptions" placeholder="换给谁" style="width: 200px" data-testid="duty-swap-to" />
              <n-button type="primary" round data-testid="duty-swap-create" @click="onSwapRequest">
                发起换班
              </n-button>
            </n-space>
            <n-empty v-if="!roster.swap_requests.length" description="暂无换班申请" style="padding: 12px 0" />
            <table v-else class="ios-table" style="margin-top: 8px">
              <thead>
                <tr><th>日期</th><th>原值日</th><th>换给</th><th>状态</th><th>操作</th></tr>
              </thead>
              <tbody>
                <tr v-for="r in roster.swap_requests" :key="r.id" data-testid="duty-swap-row">
                  <td>{{ r.date }}</td>
                  <td>{{ r.from_teacher_name }}</td>
                  <td>{{ r.to_teacher_name }}</td>
                  <td>{{ r.status === 'pending' ? '待对方同意' : r.status === 'approved' ? '已同意' : '已拒绝' }}</td>
                  <td>
                    <n-space v-if="r.status === 'pending'">
                      <n-button size="small" text type="primary" data-testid="duty-swap-approve" @click="onApprove(r.id)">
                        同意
                      </n-button>
                      <n-button size="small" text data-testid="duty-swap-reject" @click="onReject(r.id)">
                        拒绝
                      </n-button>
                    </n-space>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
        <n-text v-else-if="loading" depth="3">加载中…</n-text>
      </div>
    </div>
  </section>
</template>
