<script setup lang="ts">
import { NButton, NEmpty, NSpace, NSwitch, NText, useMessage } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import { examNoRange, getExam, listArrangements } from '@/api/exam'
import type { ArrangementItem, ExamDetail } from '@/api/exam'

// 考场门贴与桌贴打印页(KW-21):门贴每考场一张(考场号、考生起止号,
// 按 exam_no 的起止);桌贴每座位一张(考号、姓名)。是否使用桌贴请
// 学校确认,默认同时提供两种。版面照抄课表打印页:白底黑框 + @media print
// + window.print。考号为空时起止号显示“—”,不崩。

const message = useMessage()
const route = useRoute()
const router = useRouter()
const examId = Number(route.params.id)

const exam = ref<ExamDetail | null>(null)
const arrangements = ref<ArrangementItem[]>([])
const loading = ref(false)
const showDeskLabels = ref(true)

interface RoomGroup {
  room_id: number
  room_name: string
  items: ArrangementItem[]
  range: { start: string; end: string } | null
}
const roomGroups = computed<RoomGroup[]>(() => {
  const map = new Map<number, RoomGroup>()
  for (const a of arrangements.value) {
    let g = map.get(a.room_id)
    if (!g) {
      g = { room_id: a.room_id, room_name: a.room_name, items: [], range: null }
      map.set(a.room_id, g)
    }
    g.items.push(a)
  }
  const groups = [...map.values()]
  for (const g of groups) {
    g.items.sort((a, b) => (a.seat_no ?? 0) - (b.seat_no ?? 0))
    g.range = examNoRange(g.items.map((a) => a.exam_no))
  }
  groups.sort((a, b) => a.room_name.localeCompare(b.room_name, 'zh-CN'))
  return groups
})

function goBack() {
  void router.push({ name: 'exam-exam-arrange', params: { id: examId } })
}
function doPrint() {
  window.print()
}

onMounted(async () => {
  loading.value = true
  try {
    exam.value = await getExam(examId)
    arrangements.value = (await listArrangements(examId)).items
  } catch (e) {
    message.error((e as ApiError).detail || '门贴与桌贴加载失败')
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="sheet">
    <div class="no-print toolbar">
      <n-button text type="primary" @click="goBack">← 考场编排</n-button>
      <n-space :wrap="true" align="center" style="flex: 1; justify-content: flex-end">
        <n-space align="center" :wrap="false">
          <n-text style="font-size: 13px">同时打印桌贴</n-text>
          <n-switch v-model:value="showDeskLabels" data-testid="labels-desk-switch" />
        </n-space>
        <n-button type="primary" data-testid="labels-print-btn" @click="doPrint">打印</n-button>
      </n-space>
    </div>
    <n-text depth="3" class="no-print" style="font-size: 12px; display: block; margin-bottom: 12px">
      是否使用桌贴请学校确认,默认同时提供门贴与桌贴。门贴起止号按考号起止。
    </n-text>

    <h1 v-if="exam" class="head">{{ exam.name }} · 考场门贴与桌贴</h1>
    <p v-if="loading" class="empty">载入中…</p>
    <n-empty v-else-if="roomGroups.length === 0" description="暂无编排结果,请先完成考场编排" />

    <div v-for="g in roomGroups" :key="g.room_id" class="room-block">
      <div class="door-label" data-testid="door-label">
        <div class="door-title">考 场</div>
        <div class="door-room">{{ g.room_name }}</div>
        <div class="door-range">
          考生起止号:{{ g.range ? `${g.range.start} — ${g.range.end}` : '—' }}
        </div>
        <div class="door-count">共 {{ g.items.length }} 人</div>
      </div>
      <div v-if="showDeskLabels" class="desk-grid">
        <div v-for="a in g.items" :key="a.id" class="desk-label" data-testid="desk-label">
          <div class="desk-no">{{ a.exam_no ?? '—' }}</div>
          <div class="desk-name">{{ a.student_name }}</div>
          <div class="desk-sub">{{ g.room_name }} · {{ a.seat_no ?? '—' }} 号</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sheet {
  max-width: 820px;
  margin: 0 auto;
  padding: 24px;
  color: #000;
  background: #fff;
  font-family: "Microsoft YaHei", "Microsoft JhengHei", "PingFang SC", "PingFang TC", sans-serif;
}
.toolbar { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; }
.head { text-align: center; font-size: 19px; font-weight: 600; letter-spacing: 2px; margin: 0 0 16px; }
.room-block { margin-bottom: 24px; }
.door-label {
  border: 2px solid #000;
  text-align: center;
  padding: 20px 12px;
  margin-bottom: 16px;
  page-break-inside: avoid;
}
.door-title { font-size: 18px; letter-spacing: 12px; }
.door-room { font-size: 44px; font-weight: 700; margin: 8px 0; }
.door-range { font-size: 18px; font-weight: 600; }
.door-count { font-size: 14px; margin-top: 6px; }
.desk-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
.desk-label {
  border: 1px solid #000;
  text-align: center;
  padding: 10px 6px;
  page-break-inside: avoid;
}
.desk-no { font-size: 17px; font-weight: 700; }
.desk-name { font-size: 16px; margin-top: 4px; }
.desk-sub { font-size: 12px; color: #444; margin-top: 4px; }
.empty { text-align: center; padding: 40px 0; font-size: 15px; }

@media print {
  @page { size: A4 portrait; margin: 12mm; }
  .no-print { display: none !important; }
  .sheet { max-width: none; padding: 0; }
  .door-label, .desk-label { break-inside: avoid; page-break-inside: avoid; }
}
</style>

<style>
/* 打印页套在 MainLayout 内:打印时隐藏侧边栏与顶栏,只留本页内容。 */
@media print {
  .n-layout-sider, .app-header { display: none !important; }
}
</style>
