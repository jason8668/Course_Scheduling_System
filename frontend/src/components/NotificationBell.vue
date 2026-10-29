<script setup lang="ts">
import { NBadge, NButton, NEmpty, NPopover, NScrollbar, NSpace, NTag, NText, useMessage } from 'naive-ui'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { acknowledge, markRead, myNotifications } from '@/api/notifications'
import type { Notification } from '@/api/notifications'
import { publishedSemesters } from '@/api/timetables'
import { listSemesters } from '@/api/semesters'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const message = useMessage()

const POLL_MS = 20000 // 站内通知轮询;铃铛不需即时,20 秒足矣

const sid = ref<number | null>(null)
const items = ref<Notification[]>([])
const unread = ref(0)
let timer: ReturnType<typeof setInterval> | null = null

const canManage = computed(() =>
  auth.hasRole('admin') || auth.hasRole('director'))

async function resolveSemester() {
  // 教师看已发布课表的学期;管理者看全部学期。取最近一个。
  const list = canManage.value ? await listSemesters() : await publishedSemesters()
  sid.value = list[0]?.id ?? null
}

async function refresh() {
  if (sid.value === null) return
  try {
    const data = await myNotifications(sid.value)
    items.value = data.items
    unread.value = data.unread
  } catch {
    // 静默:铃铛不该打断用户
  }
}

onMounted(async () => {
  await resolveSemester()
  await refresh()
  timer = setInterval(refresh, POLL_MS)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
})

async function onOpen(show: boolean) {
  if (show) await refresh()
}

async function onAcknowledge(n: Notification) {
  await acknowledge(n.id)
  message.success('已送出确认回复')
  await refresh()
}

async function onRead(n: Notification) {
  if (n.read_at) return
  await markRead(n.id)
  await refresh()
}

const TYPE_TAG: Record<string, string> = {
  substitution_assigned: '代课通知',
  substitution_cancelled: '代课取消',
  leave_registered: '请假登记',
  leave_cancelled: '销假',
  timetable_published: '课表发布',
}
</script>

<template>
  <n-popover trigger="click" placement="bottom-end" @update:show="onOpen">
    <template #trigger>
      <n-badge :value="unread" :max="99" data-testid="notif-badge">
        <button
          type="button" class="bell-btn" :class="{ 'has-unread': unread > 0 }"
          data-testid="notif-bell" aria-label="通知"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.7 21a2 2 0 0 1-3.4 0" /></svg>
        </button>
      </n-badge>
    </template>

    <div style="width: min(360px, 80vw)">
      <n-empty v-if="!items.length" description="没有通知" style="padding: 24px 0" />
      <n-scrollbar v-else style="max-height: 60vh">
        <n-space vertical size="small" style="padding-right: 8px">
          <div
            v-for="n in items" :key="n.id" data-testid="notif-item"
            style="border-bottom: 1px solid var(--n-border-color, #eee); padding-bottom: 8px"
            @mouseenter="onRead(n)"
          >
            <n-space align="center" size="small">
              <n-tag size="tiny" :type="n.acknowledged_at ? 'success' : 'warning'">
                {{ TYPE_TAG[n.type] ?? '通知' }}
              </n-tag>
              <n-text v-if="!n.read_at" type="error" style="font-size: 12px">● 未读</n-text>
            </n-space>
            <div style="font-weight: 600; margin: 2px 0">{{ n.title }}</div>
            <n-text depth="3" style="font-size: 13px; white-space: pre-wrap">{{ n.body }}</n-text>
            <div style="margin-top: 6px">
              <n-tag v-if="n.acknowledged_at" size="small" type="success">已确认收到</n-tag>
              <n-button
                v-else size="tiny" type="primary" data-testid="notif-ack"
                @click="onAcknowledge(n)"
              >
                确认收到
              </n-button>
            </div>
          </div>
        </n-space>
      </n-scrollbar>
    </div>
  </n-popover>
</template>

<style scoped>
/* 顶栏玻璃圆钮:与「校历」玻璃药丸同一种材质,无未读时是中性玻璃,
   有未读时透出苹果蓝,铃铛用描边线条图标,不用 emoji,与整站风格统一。 */
.bell-btn {
  width: 32px; height: 32px; border-radius: 50%;
  display: inline-flex; align-items: center; justify-content: center;
  color: #1c1c1e; cursor: pointer;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.75), rgba(255, 255, 255, 0.5));
  -webkit-backdrop-filter: blur(16px) saturate(180%);
  backdrop-filter: blur(16px) saturate(180%);
  border: 1px solid rgba(255, 255, 255, 0.9);
  box-shadow: 0 4px 14px rgba(30, 60, 120, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.9);
}
.bell-btn:hover { background: linear-gradient(180deg, rgba(255, 255, 255, 0.9), rgba(255, 255, 255, 0.65)); }
.bell-btn.has-unread {
  color: #007aff;
  background: linear-gradient(180deg, rgba(0, 122, 255, 0.16), rgba(0, 122, 255, 0.08));
  box-shadow: 0 4px 16px rgba(0, 122, 255, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.9);
}
</style>
