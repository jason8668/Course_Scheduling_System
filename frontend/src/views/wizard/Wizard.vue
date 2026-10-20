<script setup lang="ts">
import {
  NAlert, NButton, NCard, NDatePicker, NGrid, NGridItem, NInputNumber, NResult, NSelect,
  NSpace, NStatistic, NStep, NSteps, NText, useMessage,
} from 'naive-ui'
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import { demoDataStatus, loadDemoData } from '@/api/assignments'
import { createSemester, getSemester, listTemplates } from '@/api/semesters'
import { PRIMARY } from '@/theme'
import type { Semester, Template } from '@/api/semesters'
import { getSemesterSummary } from '@/api/wizard'
import type { SemesterSummary } from '@/api/wizard'
import { useWizardStore } from '@/stores/wizard'
import ImportTab from '@/views/basedata/ImportTab.vue'

const router = useRouter()
const message = useMessage()
const wizard = useWizardStore()

const step = ref(0)
const templates = ref<Template[]>([])
const templateKey = ref<string | null>(null)
const year = ref(115)
const term = ref(1)
// 学期起讫日期:请假展开、今日看板与调代课都以它为准,建立时就要填(用户回报 #15)
const startDate = ref<string | null>(null)
const endDate = ref<string | null>(null)
const semesterId = ref<number | null>(null)
const semester = ref<Semester | null>(null)
const summary = ref<SemesterSummary | null>(null)
const busy = ref(false)

const termOptions = [
  { label: '第 1 学期', value: 1 },
  { label: '第 2 学期', value: 2 },
]

onMounted(async () => {
  templates.value = await listTemplates()
  if (!wizard.loaded) await wizard.fetch()
  if (wizard.state) {
    step.value = wizard.state.current_step
    semesterId.value = wizard.state.semester_id
    if (semesterId.value) await loadSemester(semesterId.value)
  }
  // 示范资料仅管理员可载;其他角色查询会 403,静静略过即可
  try {
    const demo = await demoDataStatus()
    demoAvailable.value = demo.available
    demoSchool.value = demo.school_name
  } catch {
    demoAvailable.value = false
  }
})

async function loadSemester(id: number) {
  semester.value = await getSemester(id)
  summary.value = await getSemesterSummary(id)
}

async function persistStep() {
  await wizard.patch({ current_step: step.value })
}

async function goNext() {
  // 第 2 步(学年学期)→ 建立学期
  if (step.value === 1 && !semesterId.value) {
    if (!templateKey.value) {
      message.warning('请先于上一步选择学制范本')
      return
    }
    if (!startDate.value || !endDate.value) {
      message.warning('请填学期起讫日期(请假与调代课需要)')
      return
    }
    busy.value = true
    try {
      const sem = await createSemester({
        academic_year: year.value, term: term.value, template_key: templateKey.value,
        start_date: startDate.value, end_date: endDate.value,
      })
      semesterId.value = sem.id
      await wizard.patch({ semester_id: sem.id })
      await loadSemester(sem.id)
    } catch (e) {
      message.error((e as ApiError).detail || '建立学期失败')
      busy.value = false
      return
    }
    busy.value = false
  }
  step.value = Math.min(step.value + 1, 4)
  if (step.value === 4 && semesterId.value) await loadSemester(semesterId.value)
  await persistStep()
}

async function goPrev() {
  step.value = Math.max(step.value - 1, 0)
  await persistStep()
}

async function finish() {
  await wizard.patch({ completed: true })
  message.success('初始设置完成')
  router.push({ name: 'basedata' })
}

// 示范资料入口。放在精灵里是因为:路由守卫会把「精灵未完成」的用户一律导来这页,
// 所以第一次登录的人根本到不了系统管理——那颗按钮摆在那里等于没人看得到。
const demoAvailable = ref(false)
const demoSchool = ref('')
const loadingDemo = ref(false)

async function onLoadDemo() {
  loadingDemo.value = true
  try {
    const r = await loadDemoData()
    await wizard.fetch()
    message.success(
      `已建立 ${r.classes} 班、${r.teachers} 位教师、${r.assignments} 笔配课。`
      + '可以直接去「自动排课」试跑了。',
      { duration: 8000 },
    )
    router.push({ name: 'dashboard' })
  } catch (e) {
    message.error((e as ApiError).message || '载入失败')
  } finally {
    loadingDemo.value = false
  }
}

async function skip() {
  await wizard.patch({ completed: true })
  router.push({ name: 'dashboard' })
}

function openPeriodEditor() {
  const table = semester.value?.period_tables.find((t) => t.is_default)
  if (table) router.push({ name: 'period-table-editor', params: { id: table.id } })
}
</script>

<template>
  <div style="max-width: 860px; margin: 24px auto; padding: 0 16px">
    <n-space vertical size="large">
      <n-space justify="space-between" align="center">
        <h1 style="margin: 0">设置精灵</h1>
        <n-button quaternary @click="skip">略过,稍后再设置</n-button>
      </n-space>

      <n-steps :current="step + 1" size="small">
        <n-step title="学制范本" />
        <n-step title="学年学期" />
        <n-step title="节次表" />
        <n-step title="导入资料" />
        <n-step title="完成" />
      </n-steps>

      <n-card>
        <!-- Step 0:学制范本 -->
        <template v-if="step === 0">
          <n-alert
            v-if="demoAvailable" type="info" title="只是想先试看看这套系统?"
            style="margin-bottom: 18px"
          >
            <n-space vertical size="small">
              <n-text>
                可以先载入一所完整的示范初中「{{ demoSchool }}」——18 班、57 位教师、
                246 笔配课全部建好,不必输入任何资料就能直接跑自动排课,
                把排课、调代课、导出、备份整套流程玩过一遍。
              </n-text>
              <n-text depth="3" style="font-size: 12px">
                之后要正式使用时,重新安装一套干净的系统即可;
                示范资料只能在「尚未建立任何学期」的系统上载入。
              </n-text>
              <div>
                <n-button
                  type="primary" size="small" :loading="loadingDemo"
                  data-testid="wizard-demo-load" @click="onLoadDemo"
                >
                  载入示范资料
                </n-button>
              </div>
            </n-space>
          </n-alert>
          <n-text>请选择贵校的学制,系统将自动带入对应的节次表与科目清单。</n-text>
          <n-grid :cols="2" :x-gap="12" :y-gap="12" style="margin-top: 16px">
            <n-grid-item v-for="t in templates" :key="t.key">
              <n-card
                hoverable
                :data-testid="`tpl-${t.key}`"
                :style="{
                  cursor: 'pointer',
                  borderColor: templateKey === t.key ? 'var(--n-color-target)' : undefined,
                  outline: templateKey === t.key ? `2px solid ${PRIMARY}` : 'none',
                }"
                @click="templateKey = t.key"
              >
                <strong>{{ t.name }}</strong>
                <div><n-text depth="3">{{ t.minutes_per_period }} 分/节 · {{ t.subject_count }} 科</n-text></div>
              </n-card>
            </n-grid-item>
          </n-grid>
        </template>

        <!-- Step 1:学年学期 -->
        <template v-else-if="step === 1">
          <n-space vertical>
            <n-text>设置本学期的学年度与学期别。</n-text>
            <n-space align="center">
              <n-text>学年度</n-text>
              <n-input-number v-model:value="year" data-testid="wizard-year" :min="100" :max="200" :disabled="!!semesterId" style="width: 120px" />
              <n-select v-model:value="term" :options="termOptions" :disabled="!!semesterId" style="width: 140px" />
            </n-space>
            <n-space align="center">
              <n-text>起讫日期</n-text>
              <n-date-picker
                v-model:formatted-value="startDate" value-format="yyyy-MM-dd" type="date"
                placeholder="开学日" style="width: 150px" :disabled="!!semesterId"
                data-testid="wizard-start"
              />
              <n-text>~</n-text>
              <n-date-picker
                v-model:formatted-value="endDate" value-format="yyyy-MM-dd" type="date"
                placeholder="结业日" style="width: 150px" :disabled="!!semesterId"
                data-testid="wizard-end"
              />
            </n-space>
            <n-text depth="3" style="font-size: 13px">
              依贵校校历填写。请假只能登记在这个范围内,之后可在「学期与节次表」修改。
            </n-text>
            <n-text v-if="semesterId" type="success">已建立:{{ semester?.label }}</n-text>
          </n-space>
        </template>

        <!-- Step 2:节次表 -->
        <template v-else-if="step === 2">
          <n-space vertical>
            <n-text>已依范本带入默认节次表。可先确认,若需调整(如周三下午不排课)可开启编辑器。</n-text>
            <div v-if="semester">
              <n-text strong>{{ semester.period_tables[0]?.name }}</n-text>
              <n-text depth="3">
                (共 {{ semester.period_tables[0]?.periods.length ?? 0 }} 格,每周
                {{ semester.period_tables[0]?.num_weekdays ?? 5 }} 天)
              </n-text>
            </div>
            <n-button @click="openPeriodEditor">开启节次表编辑器</n-button>
            <n-text depth="3">提示:离开编辑器后回到本精灵会自动回到此步骤。</n-text>
          </n-space>
        </template>

        <!-- Step 3:导入资料 -->
        <template v-else-if="step === 3">
          <n-space vertical>
            <n-text>下载范本填写后上传,批次建立教师、班级与科目(可略过,稍后于基础资料补建)。</n-text>
            <ImportTab v-if="semesterId" :semester-id="semesterId" />
          </n-space>
        </template>

        <!-- Step 4:完成 -->
        <template v-else>
          <n-result status="success" title="初始设置即将完成" description="以下是目前已建立的资料摘要">
            <template #footer>
              <n-space justify="center" size="large">
                <n-statistic label="科目" :value="summary?.subjects ?? 0" />
                <n-statistic label="教师" :value="summary?.teachers ?? 0" />
                <n-statistic label="班级" :value="summary?.classes ?? 0" />
                <n-statistic label="场地" :value="summary?.rooms ?? 0" />
              </n-space>
            </template>
          </n-result>
        </template>
      </n-card>

      <n-space justify="space-between">
        <n-button data-testid="wizard-prev" :disabled="step === 0" @click="goPrev">上一步</n-button>
        <n-button v-if="step < 4" data-testid="wizard-next" type="primary" :loading="busy" @click="goNext">
          下一步
        </n-button>
        <n-button v-else data-testid="wizard-finish" type="primary" @click="finish">
          完成,前往基础资料
        </n-button>
      </n-space>
    </n-space>
  </div>
</template>
