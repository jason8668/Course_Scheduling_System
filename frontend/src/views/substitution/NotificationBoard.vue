<script setup lang="ts">
import { NButton, NCheckbox, NEmpty, NSelect, NSpace, NTag, NText, useMessage } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { notificationBoard, remind } from '@/api/notifications'
import type { BoardEntry } from '@/api/notifications'
import { listSemesters } from '@/api/semesters'

const message = useMessage()

const semesters = ref<{ id: number; label: string }[]>([])
const sid = ref<number | null>(null)
const entries = ref<BoardEntry[]>([])
const unackOnly = ref(true) // 默认只看未确认——那才是组长要追的

const semesterOptions = computed(() => semesters.value.map((s) => ({ label: s.label, value: s.id })))

const TYPE_LABEL: Record<string, string> = {
  substitution_assigned: '代课通知',
  substitution_cancelled: '代课取消',
  leave_registered: '请假登记',
  leave_cancelled: '销假',
  timetable_published: '课表发布',
}

async function reload() {
  if (sid.value === null) return
  entries.value = await notificationBoard(sid.value, { unacknowledgedOnly: unackOnly.value })
}

async function onSemesterChange(id: number) {
  sid.value = id
  await reload()
}

onMounted(async () => {
  semesters.value = await listSemesters()
  if (semesters.value.length) await onSemesterChange(semesters.value[0].id)
})

async function onRemind(e: BoardEntry) {
  try {
    await remind(e.id)
    message.success(`已再次提醒 ${e.teacher_name}`)
    await reload()
  } catch (err) {
    message.error((err as { message?: string }).message || '提醒失败')
  }
}

function ackTag(e: BoardEntry): { type: string; label: string } {
  if (e.acknowledged_at) return { type: 'success', label: '已确认' }
  if (e.read_at) return { type: 'info', label: '已读未确认' }
  return { type: 'warning', label: '未读' }
}
</script>

<template>
  <div class="ios-page">
    <n-space align="center">
      <h1 class="ios-title">通知确认看板</h1>
      <n-select
        :value="sid" :options="semesterOptions" style="width: 220px"
        placeholder="选择学期" @update:value="onSemesterChange"
      />
      <n-checkbox v-model:checked="unackOnly" data-testid="board-unackonly" @update:checked="reload">
        只看未确认
      </n-checkbox>
    </n-space>

    <n-empty v-if="!entries.length" description="没有符合条件的通知" />
    <table v-else class="ios-table" data-testid="board-table">
      <thead>
        <tr><th>教师</th><th>类型</th><th>内容</th><th>状态</th><th>操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="e in entries" :key="e.id" data-testid="board-row">
          <td>{{ e.teacher_name }}</td>
          <td>{{ TYPE_LABEL[e.type] ?? e.type }}</td>
          <td>{{ e.title }}</td>
          <td>
            <n-tag size="small" :type="ackTag(e).type as never">{{ ackTag(e).label }}</n-tag>
          </td>
          <td>
            <n-button
              v-if="!e.acknowledged_at" size="tiny" data-testid="board-remind"
              @click="onRemind(e)"
            >
              再次提醒
            </n-button>
            <n-text v-else depth="3">—</n-text>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
