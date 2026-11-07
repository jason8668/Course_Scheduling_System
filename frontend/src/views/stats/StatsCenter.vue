<script setup lang="ts">
import { NDatePicker, NRadioButton, NRadioGroup, NSelect, NSpace } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { listSemesters } from '@/api/semesters'
import type { SemesterListItem } from '@/api/semesters'
import StatsNotifyCard from '@/components/stats/StatsNotifyCard.vue'
import StatsSubstituteCard from '@/components/stats/StatsSubstituteCard.vue'
import StatsTeachingCard from '@/components/stats/StatsTeachingCard.vue'

export type StatsScope = 'month' | 'semester' | 'custom'

const semesters = ref<SemesterListItem[]>([])
const sid = ref<number | null>(null)
const scope = ref<StatsScope>('month')
const customRange = ref<[number, number] | null>(null)
const semesterOptions = computed(() =>
  semesters.value.map((s) => ({ label: s.label, value: s.id })))
const semester = computed(() => semesters.value.find((s) => s.id === sid.value) ?? null)

function fmtDate(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}
// 范围由中心页统一算,三块卡片都跟著走:本月 = 本月 1 日 ~ 今天,
// 本学期 = 所选学期的起讫日,自定义 = 自选日期区间。
const dateFrom = computed<string | null>(() => {
  if (scope.value === 'month') {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
  }
  if (scope.value === 'semester') return semester.value?.start_date ?? null
  return customRange.value ? fmtDate(new Date(customRange.value[0])) : null
})
const dateTo = computed<string | null>(() => {
  if (scope.value === 'month') return fmtDate(new Date())
  if (scope.value === 'semester') return semester.value?.end_date ?? null
  return customRange.value ? fmtDate(new Date(customRange.value[1])) : null
})
onMounted(async () => {
  semesters.value = await listSemesters()
  sid.value = semesters.value[0]?.id ?? null
})
</script>

<template>
  <div class="ios-page">
    <h1 class="ios-title">
      统计中心
    </h1>
    <div class="ios-subtitle">
      代课课时、教学课时、通知确认集中在一页，每个数字都标口径
    </div>
    <n-space align="center" :wrap="true" style="margin-top: 16px">
      <span style="font-size: 13px; font-weight: 600; color: rgba(60,60,67,0.6)">一步 · 选学期</span>
      <n-select
        :value="sid" :options="semesterOptions" placeholder="选择学期"
        style="width: 220px" @update:value="(v: number) => { sid = v }"
      />
      <n-radio-group v-model:value="scope" style="margin-left: 8px">
        <n-radio-button value="month" data-testid="scope-month">
          本月
        </n-radio-button>
        <n-radio-button value="semester" data-testid="scope-semester">
          本学期
        </n-radio-button>
        <n-radio-button value="custom" data-testid="scope-custom">
          自定义
        </n-radio-button>
      </n-radio-group>
      <n-date-picker
        v-if="scope === 'custom'" v-model:value="customRange" type="daterange"
        style="width: 260px" data-testid="custom-range"
      />
    </n-space>

    <section class="ios-section">
      <div class="ios-section-title">
        <span>二 · 代课课时</span>
      </div>
      <div class="ios-card">
        <div class="ios-card-body">
          <StatsSubstituteCard :semester-id="sid" :scope="scope" :date-from="dateFrom" :date-to="dateTo" />
        </div>
      </div>
    </section>

    <section class="ios-section" style="animation-delay: 60ms">
      <div class="ios-section-title">
        <span>三 · 教学课时（实际上课）</span>
      </div>
      <div class="ios-card">
        <div class="ios-card-body">
          <StatsTeachingCard :semester-id="sid" :scope="scope" :date-from="dateFrom" :date-to="dateTo" />
        </div>
      </div>
    </section>

    <section class="ios-section" style="animation-delay: 120ms">
      <div class="ios-section-title">
        <span>四 · 通知确认</span>
      </div>
      <div class="ios-card">
        <div class="ios-card-body">
          <StatsNotifyCard :semester-id="sid" :scope="scope" :date-from="dateFrom" :date-to="dateTo" />
        </div>
      </div>
    </section>
  </div>
</template>
