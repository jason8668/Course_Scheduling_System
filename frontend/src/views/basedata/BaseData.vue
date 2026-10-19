<script setup lang="ts">
import { NAlert, NSelect, NSpace, NTabPane, NTabs } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { listSemesters } from '@/api/semesters'
import type { SemesterListItem } from '@/api/semesters'
import ClassesTab from './ClassesTab.vue'
import ImportTab from './ImportTab.vue'
import RoomsTab from './RoomsTab.vue'
import SubjectsTab from './SubjectsTab.vue'
import TeachersTab from './TeachersTab.vue'

const semesters = ref<SemesterListItem[]>([])
const currentId = ref<number | null>(null)

const semesterOptions = computed(() =>
  semesters.value.map((s) => ({ label: s.label, value: s.id })),
)

onMounted(async () => {
  semesters.value = await listSemesters()
  if (semesters.value.length) currentId.value = semesters.value[0].id
})
</script>

<template>
  <n-space vertical size="large">
    <n-space align="center">
      <h1 style="margin: 0">基础资料</h1>
      <n-select
        v-model:value="currentId"
        :options="semesterOptions"
        placeholder="选择学期"
        style="width: 240px"
      />
    </n-space>

    <n-alert v-if="!currentId" type="info">
      请先于「学期与节次表」建立学期,再回此页维护教师、班级、科目与场地。
    </n-alert>

    <n-tabs v-else type="line" animated>
      <n-tab-pane name="teachers" tab="教师">
        <TeachersTab :key="`t-${currentId}`" :semester-id="currentId" />
      </n-tab-pane>
      <n-tab-pane name="classes" tab="班级">
        <ClassesTab :key="`c-${currentId}`" :semester-id="currentId" />
      </n-tab-pane>
      <n-tab-pane name="subjects" tab="科目">
        <SubjectsTab :key="`s-${currentId}`" :semester-id="currentId" />
      </n-tab-pane>
      <n-tab-pane name="rooms" tab="场地">
        <RoomsTab :key="`r-${currentId}`" :semester-id="currentId" />
      </n-tab-pane>
      <n-tab-pane name="import" tab="批次导入">
        <ImportTab :key="`i-${currentId}`" :semester-id="currentId" />
      </n-tab-pane>
    </n-tabs>
  </n-space>
</template>
