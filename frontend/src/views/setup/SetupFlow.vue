<script setup lang="ts">
import { NSelect, NSpace } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { listSemesters } from '@/api/semesters'
import type { SemesterListItem } from '@/api/semesters'
import SetupBasedataCard from '@/components/setup/SetupBasedataCard.vue'
import SetupPeriodTablesCard from '@/components/setup/SetupPeriodTablesCard.vue'
import SetupReviewCard from '@/components/setup/SetupReviewCard.vue'
import SetupSemesterCard from '@/components/setup/SetupSemesterCard.vue'

const semesters = ref<SemesterListItem[]>([])
const sid = ref<number | null>(null)
const semesterOptions = computed(() =>
  semesters.value.map((s) => ({ label: s.label, value: s.id })))

async function reload() {
  semesters.value = await listSemesters()
  if (!semesters.value.find((s) => s.id === sid.value)) {
    sid.value = semesters.value[0]?.id ?? null
  }
}
onMounted(reload)
async function onCreated(id: number) {
  await reload()
  sid.value = id
}
async function onDeleted() {
  sid.value = null
  await reload()
}
</script>

<template>
  <div class="ios-page">
    <h1 class="ios-title">
      开学建置
    </h1>
    <div class="ios-subtitle">
      新学期开学一条流：建学期 → 节次表 → 基础资料 → 检查，不用来回换页面
    </div>
    <n-space align="center" :wrap="true" style="margin-top: 16px">
      <n-select
        :value="sid" :options="semesterOptions" placeholder="选择学期"
        style="width: 220px" @update:value="(v: number) => { sid = v }"
      />
    </n-space>

    <section class="ios-section">
      <div class="ios-section-title">
        <span>1 · 学期</span>
      </div>
      <div class="ios-card">
        <div class="ios-card-body">
          <SetupSemesterCard
            :semesters="semesters" :semester-id="sid"
            @select="(v: number) => { sid = v }" @created="onCreated" @deleted="onDeleted"
          />
        </div>
      </div>
    </section>

    <section class="ios-section" style="animation-delay: 60ms">
      <div class="ios-section-title">
        <span>2 · 节次表</span>
      </div>
      <div class="ios-card">
        <div class="ios-card-body">
          <SetupPeriodTablesCard :semester-id="sid" />
        </div>
      </div>
    </section>

    <section class="ios-section" style="animation-delay: 120ms">
      <div class="ios-section-title">
        <span>3 · 基础资料</span>
      </div>
      <div class="ios-card">
        <div class="ios-card-body">
          <SetupBasedataCard :semester-id="sid" />
        </div>
      </div>
    </section>

    <section class="ios-section" style="animation-delay: 180ms">
      <div class="ios-section-title">
        <span>4 · 完成检查</span>
      </div>
      <div class="ios-card">
        <div class="ios-card-body">
          <SetupReviewCard :key="`r-${sid}`" :semester-id="sid" />
        </div>
      </div>
    </section>
  </div>
</template>
