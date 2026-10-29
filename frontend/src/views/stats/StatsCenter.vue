<script setup lang="ts">
import { NSelect, NSpace } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { listSemesters } from '@/api/semesters'
import type { SemesterListItem } from '@/api/semesters'
import StatsNotifyCard from '@/components/stats/StatsNotifyCard.vue'
import StatsSubstituteCard from '@/components/stats/StatsSubstituteCard.vue'
import StatsTeachingCard from '@/components/stats/StatsTeachingCard.vue'

const semesters = ref<SemesterListItem[]>([])
const sid = ref<number | null>(null)
const semesterOptions = computed(() =>
  semesters.value.map((s) => ({ label: s.label, value: s.id })))
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
      <n-select
        :value="sid" :options="semesterOptions" placeholder="选择学期"
        style="width: 220px" @update:value="(v: number) => { sid = v }"
      />
    </n-space>

    <section class="ios-section">
      <div class="ios-section-title">
        <span>代课课时（月结）</span>
      </div>
      <div class="ios-card">
        <div class="ios-card-body">
          <StatsSubstituteCard :semester-id="sid" />
        </div>
      </div>
    </section>

    <section class="ios-section" style="animation-delay: 60ms">
      <div class="ios-section-title">
        <span>教学课时（实际上课）</span>
      </div>
      <div class="ios-card">
        <div class="ios-card-body">
          <StatsTeachingCard :semester-id="sid" />
        </div>
      </div>
    </section>

    <section class="ios-section" style="animation-delay: 120ms">
      <div class="ios-section-title">
        <span>通知确认</span>
      </div>
      <div class="ios-card">
        <div class="ios-card-body">
          <StatsNotifyCard :semester-id="sid" />
        </div>
      </div>
    </section>
  </div>
</template>
