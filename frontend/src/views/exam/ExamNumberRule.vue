<script setup lang="ts">
import {
  NAlert, NButton, NRadio, NRadioGroup, NSelect, NSpace, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref, watch } from 'vue'
import type { ApiError } from '@/api/client'
import {
  RULE_TYPE_LABELS, S_SHAPE_NO_SCORE_WARNING, generateExamNumbers, getExamNumberRule,
  saveExamNumberRule,
} from '@/api/exam'
import type { ExamNumberGenerateResult } from '@/api/exam'
import { listClassUnits } from '@/api/basedata'
import { listSemesters } from '@/api/semesters'
import type { ClassUnit } from '@/api/basedata'
import type { SemesterListItem } from '@/api/semesters'
import { useAuthStore } from '@/stores/auth'

const message = useMessage()
const auth = useAuthStore()
// 考号规则写操作只限 admin/director(后端 writer)。
const canManage = computed(() => auth.hasRole('admin') || auth.hasRole('director'))

const semesters = ref<SemesterListItem[]>([])
const semesterId = ref<number | null>(null)
const classes = ref<ClassUnit[]>([])
const semesterOptions = computed(() =>
  semesters.value.map((s) => ({ label: s.label, value: s.id })),
)
const gradeOptions = computed(() => {
  const grades = [...new Set(classes.value.map((c) => c.grade))].sort((a, b) => a - b)
  return grades.map((g) => ({ label: `${g} 年级`, value: g }))
})
const grade = ref<number | null>(null)
const ruleType = ref('by_student_no')
const loading = ref(false)
const forbidden = ref(false)
const generateResult = ref<ExamNumberGenerateResult | null>(null)
const generating = ref(false)

async function loadRule() {
  if (!semesterId.value) return
  loading.value = true
  forbidden.value = false
  generateResult.value = null
  try {
    const rule = await getExamNumberRule(semesterId.value, grade.value)
    ruleType.value = rule.rule_type
  } catch (e) {
    if ((e as ApiError).status === 403) forbidden.value = true
    else message.error((e as ApiError).detail || '加载失败')
  } finally {
    loading.value = false
  }
}

async function loadSemesterData() {
  if (!semesterId.value) return
  classes.value = await listClassUnits(semesterId.value)
  grade.value = gradeOptions.value[0]?.value ?? null
  await loadRule()
}

onMounted(async () => {
  try {
    semesters.value = await listSemesters()
    if (semesters.value.length) {
      semesterId.value = semesters.value[0].id
      await loadSemesterData()
    }
  } catch (e) {
    message.error((e as ApiError).detail || '学期加载失败')
  }
})
watch(semesterId, (v, old) => {
  if (v && v !== old) void loadSemesterData()
})
watch(grade, (v, old) => {
  if (v !== old) void loadRule()
})

async function saveRule() {
  if (!semesterId.value) return
  try {
    const rule = await saveExamNumberRule(semesterId.value, grade.value, ruleType.value)
    ruleType.value = rule.rule_type
    message.success('考号规则已保存')
  } catch (e) {
    message.error((e as ApiError).detail || '保存失败')
  }
}

async function onGenerate() {
  if (!semesterId.value || grade.value == null) {
    message.warning('请先选择年级')
    return
  }
  generating.value = true
  try {
    generateResult.value = await generateExamNumbers(semesterId.value, grade.value)
    message.success(`已生成 ${generateResult.value.generated} 人的考号`)
  } catch (e) {
    message.error((e as ApiError).detail || '生成失败')
  } finally {
    generating.value = false
  }
}
</script>

<template>
  <div class="ios-page">
    <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap">
      <h1 class="ios-title">考号规则</h1>
      <n-select
        v-model:value="semesterId"
        :options="semesterOptions"
        placeholder="选择学期"
        style="width: 240px"
      />
    </div>

    <n-alert v-if="!semesterId" type="info" style="margin-top: 16px">
      请先建立学期,再回此页设置考号规则。
    </n-alert>
    <n-alert v-else-if="forbidden" type="error" style="margin-top: 16px">
      无权查看考号规则。
    </n-alert>

    <template v-else>
      <div class="ios-card" style="margin-top: 16px">
        <div class="ios-card-body">
          <n-space vertical>
            <n-space align="center">
              <n-text>年级</n-text>
              <n-select
                v-model:value="grade" :options="gradeOptions"
                placeholder="选择年级" style="width: 160px"
              />
              <n-text depth="3" style="font-size: 13px">
                未单独设年级规则时,使用全校通用规则;默认按学号直接使用。
              </n-text>
            </n-space>
            <n-radio-group v-model:value="ruleType" :disabled="!canManage || loading">
              <n-space vertical>
                <n-radio value="by_student_no">{{ RULE_TYPE_LABELS.by_student_no }}</n-radio>
                <n-radio value="sequential">{{ RULE_TYPE_LABELS.sequential }}</n-radio>
                <n-radio value="s_shape">{{ RULE_TYPE_LABELS.s_shape }}</n-radio>
              </n-space>
            </n-radio-group>
            <n-text depth="3" style="font-size: 13px">
              考号主规则待学校选定一种;S 型编排依赖上次成绩,本批尚无成绩数据。
            </n-text>
            <n-space>
              <n-button v-if="canManage" type="primary" @click="saveRule">保存规则</n-button>
              <n-button
                v-if="canManage" :loading="generating"
                :disabled="grade == null" @click="onGenerate"
              >
                一键生成全年级考号
              </n-button>
              <n-text v-if="!canManage" depth="3" style="font-size: 13px">
                考号规则由教务设置与生成,你目前只有查看权限。
              </n-text>
            </n-space>
            <n-alert v-if="generateResult" type="success" data-testid="exam-generate-result">
              已生成 {{ generateResult.generated }} 人的考号(只编排在读学生)。
            </n-alert>
            <!-- S 型无成绩警告:后端原样返回,必须原样展示,不得改写。 -->
            <n-alert
              v-if="generateResult && generateResult.warning" type="warning"
              data-testid="exam-generate-warning"
            >
              {{ generateResult.warning }}
            </n-alert>
            <n-text
              v-if="ruleType === 's_shape'" depth="3" style="font-size: 13px"
              data-testid="exam-sshape-note"
            >
              提示:当前规则为 S 型编排;本批尚无上次成绩,生成时会显示「{{ S_SHAPE_NO_SCORE_WARNING }}」并暂按学号顺序编排。
            </n-text>
          </n-space>
        </div>
      </div>
    </template>
  </div>
</template>
