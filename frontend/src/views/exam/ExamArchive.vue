<script setup lang="ts">
import {
  NAlert, NButton, NEmpty, NInput, NPopconfirm, NSelect, NSpace, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import {
  ARCHIVE_STATUSES, BACKUP_POLICY_HINT,
  archiveReadOnlyHint, canArchiveExam, compareArchives, compareEmptyMessage,
  createArchive, deleteArchive, downloadArchive, exportBackup, formatDelta,
  formatPct, formatScore, getArchive, getExam, listArchives,
} from '@/api/exam'
import type { ExamArchive, ExamCompare } from '@/api/exam'
import { listSemesters } from '@/api/semesters'
import type { SemesterListItem } from '@/api/semesters'
import { useAuthStore } from '@/stores/auth'

const message = useMessage()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const examId = Number(route.params.id)
// 归档/取消归档/归档包下载/备份导出只限 admin/director,越权时后端回 403,前端原样展示。
const canManage = computed(() => auth.hasRole('admin') || auth.hasRole('director'))

const examName = ref('')
const examStatus = ref('')
const loading = ref(false)
const forbidden = ref(false)

function goBack() {
  void router.push({ name: 'exam-exam-detail', params: { id: examId } })
}

function fmtTime(s: string | null): string {
  if (!s) return '—'
  return s.replace('T', ' ').slice(0, 16)
}

// ── 考试归档(KW-65):一键归档、归档信息与 manifest 快照、下载归档包、取消归档 ──
const archive = ref<ExamArchive | null>(null)
const archiveLoading = ref(false)
const archiveNote = ref('')
const archiving = ref(false)
const readonlyHint = computed(() => archiveReadOnlyHint(archive.value))
const canArchive = computed(() => canArchiveExam(examStatus.value))
const manifestSubjects = computed(() => archive.value?.manifest?.subject_avgs ?? [])
const manifestBatches = computed(() => archive.value?.manifest?.publish_batches ?? [])
const manifest = computed(() => archive.value?.manifest)

async function reloadArchive() {
  archiveLoading.value = true
  try {
    archive.value = await getArchive(examId)
  } catch (e) {
    // 未归档时后端回 404,不是错误:只展示“尚未归档”
    if ((e as ApiError).status === 404) archive.value = null
    else message.error((e as ApiError).detail || '归档信息加载失败')
  } finally {
    archiveLoading.value = false
  }
}
async function onArchive() {
  if (!canArchive.value) return
  archiving.value = true
  try {
    archive.value = await createArchive(examId, archiveNote.value.trim() || null)
    archiveNote.value = ''
    message.success('已归档')
    await reloadExamStatus()
  } catch (e) {
    message.error((e as ApiError).detail || '归档失败')
  } finally {
    archiving.value = false
  }
}
async function reloadExamStatus() {
  try {
    const exam = await getExam(examId)
    examStatus.value = exam.status
  } catch {
    /* 状态刷新失败不阻断归档页,归档信息已在页内 */
  }
}
async function onDownloadArchive() {
  try {
    await downloadArchive(examId)
  } catch (e) {
    message.error((e as ApiError).detail || '下载失败')
  }
}
async function onUnarchive() {
  try {
    await deleteArchive(examId)
    message.success('已取消归档，考试状态回到已发布成绩')
    archive.value = null
    await reloadExamStatus()
  } catch (e) {
    message.error((e as ApiError).detail || '取消归档失败')
  }
}

// ── 历史考试查询与对比(KW-66):按学期/关键词/归档状态检索,选两次考试整体对比 ──
const semesters = ref<SemesterListItem[]>([])
const semesterOptions = computed(() =>
  semesters.value.map((s) => ({ label: s.label, value: s.id })),
)
const filterSemesterId = ref<number | null>(null)
const filterQ = ref('')
const filterStatus = ref<string | null>(null)
const statusOptions = ARCHIVE_STATUSES.map((s) => ({ label: s, value: s }))
const archiveItems = ref<{ exam_id: number; exam_name: string; exam_type: string; semester_id: number; status: string; archived_at: string | null; archived_by: number | null }[]>([])
const archiveTotal = ref(0)
const archivesLoading = ref(false)
async function reloadArchives() {
  archivesLoading.value = true
  try {
    const res = await listArchives({
      semesterId: filterSemesterId.value,
      q: filterQ.value || undefined,
      status: filterStatus.value,
    })
    archiveItems.value = res.items
    archiveTotal.value = res.total
  } catch (e) {
    message.error((e as ApiError).detail || '历史档案加载失败')
  } finally {
    archivesLoading.value = false
  }
}
const compareAId = ref<number | null>(null)
const compareBId = ref<number | null>(null)
const compareAName = computed(() =>
  archiveItems.value.find((i) => i.exam_id === compareAId.value)?.exam_name
  ?? (compareAId.value != null ? `考试 ${compareAId.value}` : '未选择'),
)
const compareBName = computed(() =>
  archiveItems.value.find((i) => i.exam_id === compareBId.value)?.exam_name
  ?? (compareBId.value != null ? `考试 ${compareBId.value}` : '未选择'),
)
const canCompare = computed(() =>
  compareAId.value != null && compareBId.value != null && compareAId.value !== compareBId.value,
)
const compareResult = ref<ExamCompare | null>(null)
const comparing = ref(false)
const compareEmpty = computed(() =>
  compareResult.value ? compareEmptyMessage(compareResult.value) : null,
)
async function onCompare() {
  if (!canCompare.value || compareAId.value == null || compareBId.value == null) return
  comparing.value = true
  try {
    compareResult.value = await compareArchives(compareAId.value, compareBId.value)
  } catch (e) {
    message.error((e as ApiError).detail || '对比失败')
  } finally {
    comparing.value = false
  }
}

// ── 数据备份与导出(KW-67):全量导出考务与成绩数据 Excel ──
const backupSemesterId = ref<number | null>(null)
const exporting = ref(false)
async function onExportBackup() {
  exporting.value = true
  try {
    await exportBackup(backupSemesterId.value)
    message.success('备份导出已开始下载')
  } catch (e) {
    message.error((e as ApiError).detail || '导出失败')
  } finally {
    exporting.value = false
  }
}

onMounted(async () => {
  loading.value = true
  try {
    const exam = await getExam(examId)
    examName.value = exam.name
    examStatus.value = exam.status
    filterSemesterId.value = exam.semester_id
    backupSemesterId.value = exam.semester_id
    semesters.value = await listSemesters()
    await Promise.all([reloadArchive(), reloadArchives()])
  } catch (e) {
    if ((e as ApiError).status === 403) forbidden.value = true
    else message.error((e as ApiError).detail || '加载失败')
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="ios-page">
    <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap">
      <n-button text type="primary" @click="goBack">← 考试详情</n-button>
      <h1 class="ios-title">{{ examName ? `${examName} · 归档与备份` : '归档与备份' }}</h1>
    </div>

    <n-alert v-if="forbidden" type="error" style="margin-top: 16px">
      无权查看该考试(不在你的可见范围内)。
    </n-alert>
    <n-empty v-else-if="!loading && !examName" description="找不到该考试" style="margin-top: 24px" />

    <template v-else-if="examName">
      <!-- 考试归档(KW-65) -->
      <div class="ios-section">
        <div class="ios-section-title">考试归档</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            考试结束后一键归档:参试名单、考场编排、监考表、成绩册、分析报表打包成一份档案。
          </n-text>
          <n-alert
            v-if="readonlyHint" type="info" style="margin-bottom: 12px"
            data-testid="archive-readonly-hint"
          >{{ readonlyHint }}</n-alert>

          <template v-if="archive">
            <n-text style="display: block" data-testid="archive-info">
              归档时间:{{ fmtTime(archive.archived_at) }}
              · 归档人编号:{{ archive.archived_by ?? '—' }}
              {{ archive.note ? ` · 备注:${archive.note}` : '' }}
            </n-text>
            <table class="ios-table" style="margin-top: 12px" data-testid="archive-manifest">
              <thead><tr><th>快照内容</th><th>数量 / 数值</th></tr></thead>
              <tbody>
                <tr><td>参试人数</td><td>{{ manifest?.participant_count ?? '—' }}</td></tr>
                <tr><td>考场编排数</td><td>{{ manifest?.arrangement_count ?? '—' }}</td></tr>
                <tr><td>监考安排数</td><td>{{ manifest?.invigilation_count ?? '—' }}</td></tr>
                <tr><td>成绩记录数</td><td>{{ manifest?.score_count ?? '—' }}</td></tr>
                <tr><td>总均分</td><td>{{ formatScore(manifest?.total_avg ?? null) }}</td></tr>
              </tbody>
            </table>
            <table
              v-if="manifestSubjects.length" class="ios-table" style="margin-top: 12px"
              data-testid="archive-manifest-subjects"
            >
              <thead><tr><th>科目</th><th>均分</th><th>及格率</th><th>优秀率</th></tr></thead>
              <tbody>
                <tr v-for="s in manifestSubjects" :key="s.subject_id">
                  <td>{{ s.subject_name }}</td>
                  <td>{{ formatScore(s.avg) }}</td>
                  <td>{{ formatPct(s.pass_rate) }}</td>
                  <td>{{ formatPct(s.excellent_rate) }}</td>
                </tr>
              </tbody>
            </table>
            <n-text
              v-if="manifestBatches.length" depth="3" style="font-size: 12px; display: block; margin-top: 8px"
              data-testid="archive-manifest-batches"
            >
              发布批次:
              <span v-for="b in manifestBatches" :key="`${b.scope_type}-${b.scope_value}`">
                {{ b.scope_type }}{{ b.scope_value }}({{ b.status }})
              </span>
            </n-text>
            <n-space :wrap="true" style="margin-top: 12px">
              <n-button
                v-if="canManage" type="primary" data-testid="archive-download"
                @click="onDownloadArchive"
              >下载归档包</n-button>
              <n-popconfirm v-if="canManage" @positive-click="onUnarchive">
                <template #trigger>
                  <n-button type="error" data-testid="archive-unarchive">取消归档</n-button>
                </template>
                确定取消归档?取消后考试状态回到已发布成绩。
              </n-popconfirm>
            </n-space>
          </template>

          <template v-else>
            <n-text style="display: block" data-testid="archive-not-archived">尚未归档</n-text>
            <n-text
              v-if="!canArchive" depth="3" style="font-size: 12px; display: block; margin-top: 8px"
              data-testid="archive-cannot-archive-hint"
            >
              当前状态为「{{ examStatus }}」,只有已发布成绩的考试可以归档。
            </n-text>
            <n-space v-if="canManage" :wrap="true" align="center" style="margin-top: 12px">
              <n-input
                v-model:value="archiveNote" placeholder="归档备注(选填,不超过 512 字)"
                maxlength="512" style="width: 260px"
              />
              <n-button
                type="primary" :disabled="!canArchive" :loading="archiving"
                data-testid="archive-archive-btn" @click="onArchive"
              >一键归档</n-button>
            </n-space>
          </template>
        </div></div>
      </div>

      <!-- 历史考试查询与对比(KW-66) -->
      <div class="ios-section">
        <div class="ios-section-title">历史考试查询与对比</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            按学年学期检索历史考试档案;在列表里把两次考试分别设为考试 A 与考试 B,对比整体均分与率值变化。
          </n-text>
          <n-space :wrap="true" align="center">
            <n-select
              v-model:value="filterSemesterId" :options="semesterOptions" clearable
              placeholder="学期" style="width: 200px" @update:value="reloadArchives"
            />
            <n-select
              v-model:value="filterStatus" :options="statusOptions" clearable
              placeholder="归档状态" style="width: 130px" @update:value="reloadArchives"
            />
            <n-input
              v-model:value="filterQ" placeholder="按考试名称检索" clearable
              style="width: 180px" @change="reloadArchives"
            />
            <n-button type="primary" @click="reloadArchives">检索</n-button>
          </n-space>
          <n-empty v-if="!archivesLoading && archiveItems.length === 0" description="暂无历史考试档案" style="margin-top: 12px" />
          <div v-for="item in archiveItems" :key="item.exam_id" class="ios-row" :data-testid="`archive-item-${item.exam_id}`">
            <div class="ios-row-main">
              <div class="ios-row-title">{{ item.exam_name }} · {{ item.exam_type }}</div>
              <div class="ios-row-sub">
                {{ item.status }}
                {{ item.archived_at ? ` · 已归档 ${fmtTime(item.archived_at)}` : ' · 未归档' }}
              </div>
            </div>
            <n-button
              size="small" :type="compareAId === item.exam_id ? 'primary' : 'default'"
              :data-testid="`archive-set-a-${item.exam_id}`" @click="compareAId = item.exam_id"
            >设为考试 A</n-button>
            <n-button
              size="small" :type="compareBId === item.exam_id ? 'primary' : 'default'"
              :data-testid="`archive-set-b-${item.exam_id}`" @click="compareBId = item.exam_id"
            >设为考试 B</n-button>
          </div>
          <n-text depth="3" style="font-size: 13px">共 {{ archiveTotal }} 场考试</n-text>

          <n-space :wrap="true" align="center" style="margin-top: 16px">
            <n-text data-testid="archive-compare-picked">
              考试 A:{{ compareAName }} · 考试 B:{{ compareBName }}
            </n-text>
            <n-button
              type="primary" :disabled="!canCompare" :loading="comparing"
              data-testid="archive-compare-btn" @click="onCompare"
            >对比两次考试</n-button>
          </n-space>
          <n-alert
            v-if="compareEmpty" type="info" style="margin-top: 12px"
            data-testid="archive-compare-empty"
          >{{ compareEmpty }}</n-alert>
          <template v-if="compareResult && compareResult.subjects.length">
            <table class="ios-table" style="margin-top: 12px" data-testid="archive-compare-result">
              <thead>
                <tr>
                  <th>科目</th><th>均分 A</th><th>均分 B</th><th>均分变化</th>
                  <th>及格率 A</th><th>及格率 B</th><th>及格率变化</th>
                  <th>优秀率 A</th><th>优秀率 B</th><th>优秀率变化</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="s in compareResult.subjects" :key="s.subject_id">
                  <td>{{ s.subject_name }}</td>
                  <td>{{ formatScore(s.avg_a) }}</td>
                  <td>{{ formatScore(s.avg_b) }}</td>
                  <td>{{ formatDelta(s.delta_avg) }}</td>
                  <td>{{ formatPct(s.pass_rate_a) }}</td>
                  <td>{{ formatPct(s.pass_rate_b) }}</td>
                  <td>{{ formatDelta(s.delta_pass_rate) }}</td>
                  <td>{{ formatPct(s.excellent_rate_a) }}</td>
                  <td>{{ formatPct(s.excellent_rate_b) }}</td>
                  <td>{{ formatDelta(s.delta_excellent_rate) }}</td>
                </tr>
                <tr>
                  <td>总分</td>
                  <td>{{ formatScore(compareResult.total_avg_a) }}</td>
                  <td>{{ formatScore(compareResult.total_avg_b) }}</td>
                  <td>{{ formatDelta(compareResult.delta_total_avg) }}</td>
                  <td colspan="6">—</td>
                </tr>
              </tbody>
            </table>
          </template>
        </div></div>
      </div>

      <!-- 数据备份与导出(KW-67) -->
      <div class="ios-section">
        <div class="ios-section-title">数据备份与导出</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            教务可全量导出考务与成绩数据(Excel),保证数据在学校自己手里,不被系统锁定。
          </n-text>
          <n-alert type="info" style="margin-bottom: 12px" data-testid="archive-backup-policy">
            {{ BACKUP_POLICY_HINT }}
          </n-alert>
          <n-space :wrap="true" align="center">
            <n-select
              v-model:value="backupSemesterId" :options="semesterOptions" clearable
              placeholder="全部学期" style="width: 200px"
            />
            <n-button
              v-if="canManage" type="primary" :loading="exporting"
              data-testid="archive-export-backup" @click="onExportBackup"
            >全量导出 Excel</n-button>
          </n-space>
        </div></div>
      </div>
    </template>
  </div>
</template>
