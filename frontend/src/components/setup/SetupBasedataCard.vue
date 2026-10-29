<script setup lang="ts">
import { NAlert, NTabPane, NTabs } from 'naive-ui'
import ClassesTab from '@/views/basedata/ClassesTab.vue'
import ImportTab from '@/views/basedata/ImportTab.vue'
import RoomsTab from '@/views/basedata/RoomsTab.vue'
import SubjectsTab from '@/views/basedata/SubjectsTab.vue'
import TeachersTab from '@/views/basedata/TeachersTab.vue'

defineProps<{ semesterId: number | null }>()
</script>

<template>
  <div>
    <n-alert v-if="!semesterId" type="info">
      请先在上面建立或选择学期，再回此页维护教师、班级、科目与场地。
    </n-alert>
    <n-tabs v-else type="line" animated>
      <n-tab-pane name="teachers" tab="教师">
        <TeachersTab :key="`t-${semesterId}`" :semester-id="semesterId" />
      </n-tab-pane>
      <n-tab-pane name="classes" tab="班级">
        <ClassesTab :key="`c-${semesterId}`" :semester-id="semesterId" />
      </n-tab-pane>
      <n-tab-pane name="subjects" tab="科目">
        <SubjectsTab :key="`s-${semesterId}`" :semester-id="semesterId" />
      </n-tab-pane>
      <n-tab-pane name="rooms" tab="场地">
        <RoomsTab :key="`r-${semesterId}`" :semester-id="semesterId" />
      </n-tab-pane>
      <n-tab-pane name="import" tab="批次导入">
        <ImportTab :key="`i-${semesterId}`" :semester-id="semesterId" />
      </n-tab-pane>
    </n-tabs>
  </div>
</template>
