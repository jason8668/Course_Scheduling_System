<script setup lang="ts">
import { NButton, NSelect, NSpace, NText, useMessage } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { listSemesters } from '@/api/semesters'
import type { SemesterListItem } from '@/api/semesters'
import SetupBasedataCard from '@/components/setup/SetupBasedataCard.vue'
import SetupPeriodTablesCard from '@/components/setup/SetupPeriodTablesCard.vue'
import SetupReviewCard from '@/components/setup/SetupReviewCard.vue'
import SetupSemesterCard from '@/components/setup/SetupSemesterCard.vue'
import { useWizardStore } from '@/stores/wizard'

const message = useMessage()
const router = useRouter()
const wizard = useWizardStore()

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
onMounted(async () => {
  await reload()
  if (!wizard.loaded) await wizard.fetch()
})
async function onCreated(id: number) {
  await reload()
  sid.value = id
}
async function onDeleted() {
  sid.value = null
  await reload()
}

// 首登引导改指开学建置(R7)后,新管理员走完第 4 步要点这里才算完成:
// 跟旧精灵完成按钮同一个接口(completed 置 true),否则守卫每次都会把人导回本页。
async function finishSetup() {
  if (!sid.value) return
  try {
    await wizard.patch({ completed: true })
    message.success('开学建置完成')
    router.push({ name: 'dashboard' })
  } catch {
    message.error('完成失败,请重试')
  }
}
</script>

<template>
  <div class="ios-page ios-page-narrow">
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
            @updated="reload"
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
          <n-space align="center" style="margin-top: 12px">
            <n-button
              v-if="wizard.state && !wizard.state.completed" type="primary" round
              :disabled="!sid" @click="finishSetup"
            >
              完成开学建置
            </n-button>
            <n-text v-if="wizard.state && !wizard.state.completed" depth="3" style="font-size: 12px">
              首次建置点这里完成,之后进系统不再自动跳回本页。
            </n-text>
          </n-space>
        </div>
      </div>
    </section>
  </div>
</template>
