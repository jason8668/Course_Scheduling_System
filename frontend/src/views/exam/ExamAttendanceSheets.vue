<script setup lang="ts">
import { NButton, NEmpty, NSelect, NSpace, NText, useMessage } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import { getExam, groupAttendanceByRoomSubject, listArrangements } from '@/api/exam'
import type { ArrangementItem, ExamDetail } from '@/api/exam'

// 考场名单与签到表打印页(KW-20):按考场 + 科目出表,含序号、考号、姓名、
// 班级、座位号与签到栏,供监考教师点名、核对缺考使用。
// 同时也是编排总表(KW-22)的可打印形态:用浏览器“另存为 PDF”得到 PDF。
// 版面照抄课表打印页:白底黑框表 + @media print + window.print。

const message = useMessage()
const route = useRoute()
const router = useRouter()
const examId = Number(route.params.id)

const exam = ref<ExamDetail | null>(null)
const arrangements = ref<ArrangementItem[]>([])
const loading = ref(false)
const filterSubjectId = ref<number | null>(null)
const filterRoomId = ref<number | null>(null)

const subjectOptions = computed(() => (exam.value?.subjects ?? []).map((s) => ({
  label: s.subject_name, value: s.subject_id,
})))
const roomOptions = computed(() => {
  const seen = new Map<number, string>()
  for (const a of arrangements.value) seen.set(a.room_id, a.room_name)
  return [...seen.entries()].map(([value, label]) => ({ label, value }))
})
const groups = computed(() => {
  let list = arrangements.value
  if (filterSubjectId.value != null) list = list.filter((a) => a.subject_id === filterSubjectId.value)
  if (filterRoomId.value != null) list = list.filter((a) => a.room_id === filterRoomId.value)
  return groupAttendanceByRoomSubject(list)
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
    message.error((e as ApiError).detail || '签到表加载失败')
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
        <n-select
          v-model:value="filterSubjectId" :options="subjectOptions" clearable
          placeholder="全部科目" style="width: 150px" data-testid="attendance-subject-filter"
        />
        <n-select
          v-model:value="filterRoomId" :options="roomOptions" clearable
          placeholder="全部考场" style="width: 150px" data-testid="attendance-room-filter"
        />
        <n-button type="primary" data-testid="attendance-print-btn" @click="doPrint">打印</n-button>
      </n-space>
    </div>
    <n-text depth="3" class="no-print" style="font-size: 12px; display: block; margin-bottom: 12px">
      供监考教师点名、核对缺考使用。浏览器“另存为 PDF”即为编排总表 PDF。
    </n-text>

    <h1 v-if="exam" class="head">{{ exam.name }} · 考场名单与签到表</h1>
    <p v-if="loading" class="empty">载入中…</p>
    <n-empty v-else-if="groups.length === 0" description="暂无编排结果,请先完成考场编排" />
    <div v-for="g in groups" :key="`${g.room_id}-${g.subject_id}`" class="sheet-block">
      <div class="subhead">
        <span>考场:{{ g.room_name }}</span>
        <span>科目:{{ g.subject_name ?? '—' }}</span>
        <span>人数:{{ g.items.length }}</span>
        <span>监考教师:____________</span>
      </div>
      <table class="grid">
        <thead>
          <tr><th class="ncol">序号</th><th>考号</th><th>姓名</th><th>班级</th><th class="ncol">座位号</th><th class="signcol">签到</th></tr>
        </thead>
        <tbody>
          <tr v-for="(a, i) in g.items" :key="a.id">
            <td>{{ i + 1 }}</td>
            <td>{{ a.exam_no ?? '—' }}</td>
            <td>{{ a.student_name }}</td>
            <td>{{ a.class_name ?? '—' }}</td>
            <td>{{ a.seat_no ?? '—' }}</td>
            <td class="sign" />
          </tr>
        </tbody>
      </table>
      <div class="foot">缺考人数:______ 缺考考生考号:________________________________</div>
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
.sheet-block { margin-bottom: 24px; page-break-inside: avoid; }
.subhead {
  display: flex; gap: 24px; flex-wrap: wrap;
  font-size: 15px; font-weight: 600; margin-bottom: 8px;
}
.grid { border-collapse: collapse; width: 100%; table-layout: fixed; font-size: 13px; }
.grid th, .grid td { border: 1px solid #000; padding: 5px 6px; text-align: center; }
.grid th { background: #eee; }
.grid .ncol { width: 60px; }
.grid .signcol { width: 110px; }
.sign { height: 22px; }
.foot { font-size: 13px; margin-top: 8px; }
.empty { text-align: center; padding: 40px 0; font-size: 15px; }

@media print {
  @page { size: A4 portrait; margin: 12mm; }
  .no-print { display: none !important; }
  .sheet { max-width: none; padding: 0; }
  .sheet-block { break-inside: avoid; page-break-inside: avoid; }
}
</style>

<style>
/* 打印页套在 MainLayout 内:打印时隐藏侧边栏与顶栏,只留本页内容。 */
@media print {
  .n-layout-sider, .app-header { display: none !important; }
}
</style>
