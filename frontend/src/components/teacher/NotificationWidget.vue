<script setup lang="ts">
import { NButton, NEmpty, NModal, NSpace } from 'naive-ui'
import { computed, onMounted, ref, watch } from 'vue'
import { acknowledge, markRead, myNotifications } from '@/api/notifications'
import type { Notification } from '@/api/notifications'

// 仪表板右上角通知小框(Jason 2026-10-30 定):
// 小框只显示最新一条 + 未读数,点开弹窗看全部,弹窗里才能标已读/确认收到。
// 之前通知是一整节卡片占在仪表板中间,现在改成右上角小框,不占主流程。
const props = defineProps<{ semesterId: number }>()
const notifications = ref<Notification[]>([])
const showDetail = ref(false)

const unreadCount = computed(() => notifications.value.filter((n) => !n.read_at).length)
const latest = computed(() => notifications.value[0] ?? null)

async function load() {
  const notifs = await myNotifications(props.semesterId).catch(() => ({ items: [], unread: 0 }))
  notifications.value = [...notifs.items].sort((a, b) =>
    (a.read_at ? 1 : 0) - (b.read_at ? 1 : 0))
}
async function onMarkRead(id: number) {
  await markRead(id).catch(() => {})
  await load()
}
async function onAcknowledge(id: number) {
  await acknowledge(id).catch(() => {})
  await load()
}

onMounted(() => { void load() })
watch(() => props.semesterId, () => { void load() })
</script>

<template>
  <div
    class="notif-widget" data-testid="notif-widget" role="button" tabindex="0"
    @click="showDetail = true" @keydown.enter="showDetail = true"
  >
    <div class="notif-widget-head">
      <span class="notif-widget-title">通知</span>
      <span v-if="unreadCount" class="ios-chip-warn ios-chip">{{ unreadCount }} 条未读</span>
      <span v-else class="ios-chip-gray ios-chip">无未读</span>
    </div>
    <div v-if="latest" class="notif-widget-body">
      <span v-if="!latest.read_at" class="ios-dot" />
      <span class="notif-widget-text">{{ latest.title }}</span>
    </div>
    <div v-else class="notif-widget-body ios-row-sub">
      暂无通知
    </div>
    <div class="notif-widget-hint">
      点开查看全部通知
    </div>
  </div>

  <n-modal v-model:show="showDetail" preset="card" title="通知" style="width: 560px; max-width: 92vw">
    <n-empty v-if="!notifications.length" description="暂无通知" />
    <template v-else>
      <div v-for="n in notifications" :key="n.id" class="ios-row">
        <span v-if="!n.read_at" class="ios-dot" />
        <div class="ios-row-main">
          <div style="display: flex; align-items: baseline; gap: 8px">
            <span class="ios-row-title">{{ n.title }}</span>
            <span class="ios-row-sub">{{ n.created_at?.slice(0, 16) }}</span>
          </div>
          <div class="ios-row-sub">
            {{ n.body }}
          </div>
          <n-space style="margin-top: 4px">
            <n-button v-if="!n.read_at" size="small" text type="primary" @click="onMarkRead(n.id)">
              标为已读
            </n-button>
            <n-button v-if="!n.acknowledged_at" size="small" text type="primary" @click="onAcknowledge(n.id)">
              确认收到
            </n-button>
            <span v-else class="ios-chip-green ios-chip">已确认</span>
          </n-space>
        </div>
      </div>
    </template>
  </n-modal>
</template>

<style scoped>
.notif-widget {
  width: 300px; flex-shrink: 0; cursor: pointer;
  background: rgba(255, 255, 255, 0.72);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  backdrop-filter: saturate(180%) blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.9);
  border-radius: 16px; padding: 12px 14px;
  box-shadow: 0 4px 16px rgba(30, 60, 120, 0.08);
}
.notif-widget-head { display: flex; align-items: center; gap: 8px; }
.notif-widget-title { font-size: 15px; font-weight: 600; }
.notif-widget-body { display: flex; align-items: center; gap: 6px; margin-top: 6px; }
.notif-widget-text {
  font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.notif-widget-hint { margin-top: 4px; font-size: 12px; color: rgba(60, 60, 67, 0.6); }
</style>
