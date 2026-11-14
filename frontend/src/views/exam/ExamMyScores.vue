<script setup lang="ts">
import { NAlert, NButton, NEmpty, NSelect, NSpace, NText, useMessage } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import {
  MY_SCORES_NOT_PUBLISHED, formatScore, getMyReportCard, getMyScores, listExams,
  rankVisible,
} from '@/api/exam'
import type { Exam, MyReportCard, MyScoreItem } from '@/api/exam'

// 学生/家长自助查询页(KW-55):学生/家长凭本人账号查看自己(孩子)的成绩与个人成绩单,
// 只能看本人,不能看他人(后端按账号关联的学生过滤,越权 403)。
// 未发布时后端 403,detail 原样展示,不改写;家长有多个孩子时可切换孩子。
// 排名按成绩单设置决定是否出现:后端删键,前端按“键在不在”判断,不自行补排名。

const message = useMessage()
const route = useRoute()
const router = useRouter()

const exams = ref<Exam[]>([])
const examId = ref<number | null>(null)
const items = ref<MyScoreItem[]>([])
const selectedStudentId = ref<number | null>(null)
const reportCard = ref<MyReportCard | null>(null)
const loading = ref(false)
const notPublished = ref('')
const emptyHint = ref('')

const examOptions = computed(() =>
  exams.value.map((e) => ({ label: e.name, value: e.id })),
)
const selected = computed(() =>
  items.value.find((it) => it.student_id === selectedStudentId.value) ?? items.value[0] ?? null,
)
const childOptions = computed(() =>
  items.value.map((it) => ({
    label: `${it.student_name}(${it.student_no})`, value: it.student_id,
  })),
)

function goHome() {
  void router.push({ name: 'dashboard' })
}
function doPrint() {
  window.print()
}

async function reload() {
  if (!examId.value) { items.value = []; reportCard.value = null; return }
  loading.value = true
  notPublished.value = ''
  emptyHint.value = ''
  reportCard.value = null
  try {
    const res = await getMyScores(examId.value)
    items.value = res.items
    if (items.value.length === 0) {
      emptyHint.value = '本次考试暂无你的成绩,请确认是否在参试名单中'
      return
    }
    selectedStudentId.value = items.value[0].student_id
    await reloadReportCard()
  } catch (e) {
    items.value = []
    const err = e as ApiError
    // 未发布后端 403,detail 原样展示。
    if (err.status === 403) notPublished.value = err.detail || MY_SCORES_NOT_PUBLISHED
    else message.error(err.detail || '成绩加载失败')
  } finally {
    loading.value = false
  }
}

async function reloadReportCard() {
  if (!examId.value || !selectedStudentId.value) return
  try {
    reportCard.value = await getMyReportCard(examId.value, selectedStudentId.value)
  } catch (e) {
    reportCard.value = null
    const err = e as ApiError
    if (err.status === 403) notPublished.value = err.detail || MY_SCORES_NOT_PUBLISHED
    else message.error(err.detail || '个人成绩单加载失败')
  }
}

onMounted(async () => {
  loading.value = true
  try {
    const res = await listExams()
    exams.value = res.items
    const q = route.query.exam_id ? Number(route.query.exam_id) : null
    if (q && exams.value.some((e) => e.id === q)) {
      examId.value = q
      await reload()
    }
  } catch (e) {
    message.error((e as ApiError).detail || '考试列表加载失败')
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="sheet">
    <div class="no-print toolbar">
      <n-button text type="primary" @click="goHome">← 首页</n-button>
      <h1 class="head-inline">我的成绩</h1>
      <n-space :wrap="true" align="center" style="flex: 1; justify-content: flex-end">
        <n-select
          v-model:value="examId" :options="examOptions" clearable
          placeholder="选择考试" style="width: 200px"
          data-testid="my-scores-exam-select" @update:value="reload"
        />
        <n-button
          type="primary" :disabled="!reportCard" data-testid="my-scores-print-btn"
          @click="doPrint"
        >打印成绩单</n-button>
      </n-space>
    </div>
    <n-text depth="3" class="no-print" style="font-size: 12px; display: block; margin-bottom: 12px">
      只能查看本人(孩子)的成绩;家长版是否显示排名由学校决定,教师版与家长版可能不同。
    </n-text>

    <p v-if="loading" class="empty">载入中…</p>
    <n-alert
      v-else-if="notPublished" type="warning" style="margin-bottom: 12px"
      data-testid="my-scores-not-published"
    >{{ notPublished }}</n-alert>
    <n-empty v-else-if="!examId" description="请先选择考试" />
    <n-empty v-else-if="emptyHint" :description="emptyHint" />
    <template v-else-if="selected">
      <n-space v-if="childOptions.length > 1" :wrap="true" align="center" class="no-print" style="margin-bottom: 12px">
        <span>切换孩子</span>
        <n-select
          v-model:value="selectedStudentId" :options="childOptions" style="width: 200px"
          data-testid="my-scores-child-select" @update:value="reloadReportCard"
        />
      </n-space>

      <div class="card">
        <div class="card-title">成 绩 单</div>
        <div class="card-grid">
          <div><span class="k">姓名</span>{{ selected.student_name }}</div>
          <div><span class="k">学号</span>{{ selected.student_no }}</div>
          <div><span class="k">考试</span>{{ selected.exam_name }}</div>
          <div><span class="k">总分</span>{{ formatScore(selected.total) }}</div>
          <div v-if="rankVisible(selected, 'class')"><span class="k">班级排名</span>{{ selected.class_rank }}</div>
          <div v-if="rankVisible(selected, 'grade')"><span class="k">年级排名</span>{{ selected.grade_rank }}</div>
        </div>
        <table class="grid">
          <thead><tr><th>科目</th><th>成绩</th><th>状态</th></tr></thead>
          <tbody>
            <tr v-for="s in selected.subjects" :key="s.subject_id">
              <td>{{ s.subject_name }}</td>
              <td>{{ formatScore(s.score) }}</td>
              <td>{{ s.status }}</td>
            </tr>
          </tbody>
        </table>
        <div class="card-foot">
          总分 {{ formatScore(selected.total) }} 分
          <span v-if="!rankVisible(selected, 'class') && !rankVisible(selected, 'grade')">
            · 本次成绩单不显示排名(由学校决定)
          </span>
        </div>
      </div>
    </template>
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
.head-inline { font-size: 19px; font-weight: 600; margin: 0; }
.card { border: 2px solid #000; padding: 16px 20px; page-break-inside: avoid; }
.card-title { text-align: center; font-size: 20px; font-weight: 700; letter-spacing: 8px; margin-bottom: 12px; }
.card-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 24px;
  font-size: 15px;
  margin-bottom: 10px;
}
.card-grid .k { display: inline-block; width: 64px; font-weight: 600; }
.grid { border-collapse: collapse; width: 100%; table-layout: fixed; font-size: 13px; }
.grid th, .grid td { border: 1px solid #000; padding: 5px 6px; text-align: center; }
.grid th { background: #eee; }
.card-foot { font-size: 12px; color: #444; margin-top: 10px; }
.empty { text-align: center; padding: 40px 0; font-size: 15px; }

@media print {
  @page { size: A4 portrait; margin: 12mm; }
  .no-print { display: none !important; }
  .sheet { max-width: none; padding: 0; }
  .card { break-inside: avoid; page-break-inside: avoid; }
}
</style>

<style>
/* 打印页套在 MainLayout 内:打印时隐藏侧边栏与顶栏,只留本页内容。 */
@media print {
  .n-layout-sider, .app-header { display: none !important; }
}
</style>
