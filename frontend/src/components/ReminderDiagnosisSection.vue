/**
 * 提醒诊断(管理员,系统管理页):老师说“没收到提醒”时,不用翻 worker 日志,
 * 在这里选学期、老师、日期、节次,按链一步步查断在哪一环。
 * 只读:诊断不发消息、不改资料;“发一条测试提醒”是另外的按钮,点了才真发。
 */
<script setup lang="ts">
import {
  NAlert, NButton, NDatePicker, NInputNumber, NSelect, NSpace, NTag, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref, watch } from 'vue'
import type { ApiError } from '@/api/client'
import { listTeachers } from '@/api/basedata'
import { diagnoseReminder, testSendReminder } from '@/api/reminderDiagnosis'
import type { ReminderDiagnosis } from '@/api/reminderDiagnosis'
import { listSemesters } from '@/api/semesters'

const message = useMessage()
const semesters = ref<{ label: string; value: number }[]>([])
const teachers = ref<{ label: string; value: number }[]>([])
const semesterId = ref<number | null>(null)
const teacherId = ref<number | null>(null)
const dateTs = ref<number | null>(Date.now())
const periodNo = ref<number | null>(1)
const result = ref<ReminderDiagnosis | null>(null)
const loading = ref(false)
const sending = ref(false)
const error = ref('')

function localDate(ts: number | null): string | null {
  if (ts === null) return null
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

async function loadSemesters() {
  try {
    const rows = await listSemesters()
    semesters.value = rows.map((r) => ({ label: r.label, value: r.id }))
    if (semesterId.value === null && rows.length) semesterId.value = rows[0].id
  } catch { /* 学期载入失败时留空,用户可刷新 */ }
}

async function loadTeachers() {
  if (semesterId.value === null) { teachers.value = []; return }
  try {
    const rows = await listTeachers(semesterId.value)
    teachers.value = rows.map((t) => ({ label: t.name, value: t.id }))
    // 默认先选第一位老师,省一次点击;要查别人再换下拉即可。
    if (teacherId.value === null && rows.length) teacherId.value = rows[0].id
  } catch { teachers.value = [] }
}

watch(semesterId, () => { teacherId.value = null; result.value = null; loadTeachers() })
onMounted(async () => { await loadSemesters(); await loadTeachers() })

const canDiagnose = computed(() =>
  semesterId.value !== null && teacherId.value !== null
  && dateTs.value !== null && periodNo.value !== null)

async function onDiagnose() {
  if (!canDiagnose.value) return
  loading.value = true
  error.value = ''
  try {
    result.value = await diagnoseReminder(
      semesterId.value!, teacherId.value!, localDate(dateTs.value)!, periodNo.value!,
    )
  } catch (e) {
    error.value = (e as ApiError).message || '诊断失败'
  } finally { loading.value = false }
}

async function onTestSend() {
  if (teacherId.value === null) return
  sending.value = true
  try {
    const r = await testSendReminder(teacherId.value)
    message.success(`测试提醒已发给${r.teacher_name},请到他的钉钉工作通知里确认`)
  } catch (e) {
    message.error((e as ApiError).message || '测试发送失败')
  } finally { sending.value = false }
}

function tagType(s: string): 'success' | 'warning' | 'error' {
  return s === 'ok' ? 'success' : s === 'warn' ? 'warning' : 'error'
}
</script>

<template>
  <section class="ios-section" data-testid="reminder-diagnosis">
    <div class="ios-section-title">提醒诊断(没收到提醒时查这里)</div>
    <div class="ios-card">
      <div class="ios-card-body">
        <n-space vertical>
          <n-text depth="3">
            选老师、日期、节次,一步步查:配置、任务、课表、实际有课、开关、手机号、
            通讯录、窗口、发送记录。诊断只查不发;要验证整条链通不通,点“发一条测试提醒”。
          </n-text>
          <n-space :wrap="true">
            <n-select
              v-model:value="semesterId" :options="semesters" placeholder="学期"
              style="width: 200px" data-testid="diag-semester"
            />
            <n-select
              v-model:value="teacherId" :options="teachers" placeholder="老师"
              style="width: 160px" data-testid="diag-teacher"
            />
            <n-date-picker
              v-model:value="dateTs" type="date" style="width: 160px" data-testid="diag-date"
            />
            <n-input-number
              v-model:value="periodNo" :min="1" :max="12" placeholder="节次"
              style="width: 110px" data-testid="diag-period"
            />
            <n-button
              type="primary" :disabled="!canDiagnose" :loading="loading"
              data-testid="diag-run" @click="onDiagnose"
            >
              开始诊断
            </n-button>
            <n-button
              :disabled="teacherId === null" :loading="sending"
              data-testid="diag-test-send" @click="onTestSend"
            >
              发一条测试提醒
            </n-button>
          </n-space>
          <n-text v-if="error" type="error">{{ error }}</n-text>
          <template v-if="result">
            <n-alert type="info" :show-icon="false" data-testid="diag-conclusion">
              {{ result.conclusion }}
            </n-alert>
            <n-space vertical>
              <n-space v-for="s in result.steps" :key="s.key" align="center">
                <n-tag :type="tagType(s.status)" size="small">
                  {{ s.status === 'ok' ? '通过' : s.status === 'warn' ? '注意' : '断在这里' }}
                </n-tag>
                <n-text depth="2" style="font-size: 13px">
                  {{ s.label }}: {{ s.detail }}
                </n-text>
              </n-space>
            </n-space>
          </template>
        </n-space>
      </div>
    </div>
  </section>
</template>
