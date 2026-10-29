<script setup lang="ts">
import { NButton, NEmpty, NSpace, NSwitch, NText, useMessage } from 'naive-ui'
import { computed, onMounted, ref, watch } from 'vue'
import type { ApiError } from '@/api/client'
import { notificationBoard, remind } from '@/api/notifications'
import type { BoardEntry } from '@/api/notifications'

const props = defineProps<{ semesterId: number | null }>()
const message = useMessage()

const unackOnly = ref(true)
const entries = ref<BoardEntry[]>([])
async function reload() {
  if (!props.semesterId) {
    entries.value = []
    return
  }
  entries.value = await notificationBoard(props.semesterId, { unacknowledgedOnly: unackOnly.value })
}
watch(() => props.semesterId, reload)
onMounted(reload)
const unackCount = computed(() => entries.value.filter((e) => !e.acknowledged_at).length)
async function onRemind(e: BoardEntry) {
  try {
    await remind(e.id)
    message.success('已再次提醒')
    await reload()
  } catch (err) {
    message.error((err as ApiError).detail || '提醒失败')
  }
}
</script>

<template>
  <div>
    <div class="ios-row-sub" style="margin-bottom: 8px">
      老师还没确认收到的通知都在这里；点「再次提醒」会再推一次。
    </div>
    <n-space align="center" :wrap="true" style="margin-bottom: 12px">
      <n-text>只看未确认</n-text>
      <n-switch v-model:value="unackOnly" size="small" @update:value="reload" />
      <span class="ios-chip-warn ios-chip">未确认 {{ unackCount }} 条</span>
      <n-button size="small" text type="primary" @click="reload">
        刷新
      </n-button>
    </n-space>
    <n-empty v-if="!entries.length" description="没有通知" style="padding: 12px 0" />
    <template v-else>
      <div v-for="e in entries" :key="e.id" class="ios-row">
        <div class="ios-row-main">
          <span class="ios-row-title">{{ e.title }}</span>
          <span class="ios-row-sub" style="margin-left: 8px">
            {{ e.teacher_name }} · {{ e.created_at }}
          </span>
          <span v-if="e.acknowledged_at" class="ios-chip-green ios-chip" style="margin-left: 8px">已确认</span>
          <span v-else class="ios-chip-warn ios-chip" style="margin-left: 8px">未确认</span>
          <span v-if="!e.read_at" class="ios-dot" style="margin-left: 8px" />
        </div>
        <n-button v-if="!e.acknowledged_at" size="small" text type="primary" @click="onRemind(e)">
          再次提醒
        </n-button>
      </div>
    </template>
  </div>
</template>
