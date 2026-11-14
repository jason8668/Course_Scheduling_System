<script setup lang="ts">
import {
  NAlert, NButton, NEmpty, NInput, NInputNumber, NPopconfirm, NSelect,
  NSpace, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import {
  ANALYSIS_SCOPE_LABELS, DEFAULT_ANALYSIS_SETTINGS,
  QUALITY_COMPARE_FORBIDDEN_HINT, RANK_TIE_RULE_LABELS, RANK_TIE_RULES,
  createTargetStudent, deleteTargetStudent, downloadReportPack, formatPct,
  formatScore, getAnalysisCritical, getAnalysisProgress, getAnalysisRankings,
  getAnalysisSegments, getAnalysisSettings, getAnalysisSummary, getExam,
  getGradeDistribution, getQualityCompare, getStudentTrend, getTargetTracking,
  listGradeBands, listParticipants, listSubjectThresholds, listTargetStudents,
  nextRankAfterTie, progressEmptyMessage, saveAnalysisSettings,
  saveGradeBands, saveSubjectThresholds, tieGroups, tieRuleHint,
} from '@/api/exam'
import type {
  AnalysisProgress, AnalysisSettings, AnalysisSummary, CriticalItem, ExamParticipant,
  GradeBand, GradeDistributionBand, QualityCompare, RankingItem, RankTieRule,
  Segment, StudentTrend, SubjectThreshold, TargetStudent, TargetTrackingItem,
} from '@/api/exam'
import { listClassUnits } from '@/api/basedata'
import type { ClassUnit } from '@/api/basedata'
import { useAuthStore } from '@/stores/auth'

const message = useMessage()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const examId = Number(route.params.id)
// 分析设置、阈值、等第档与目标生写操作只限 admin/director,越权时后端回 403,
// 前端原样展示;汇总、排名等读接口按可见范围过滤。
const canManage = computed(() => auth.hasRole('admin') || auth.hasRole('director'))

const examName = ref('')
const semesterId = ref(0)
const loading = ref(false)
const forbidden = ref(false)
const examSubjects = ref<{ subject_id: number; subject_name: string; full_score: number | null }[]>([])
const subjectOptions = computed(() =>
  examSubjects.value.map((s) => ({ label: s.subject_name, value: s.subject_id })),
)
const classes = ref<ClassUnit[]>([])
const classOptions = computed(() =>
  classes.value.map((c) => ({ label: `${c.grade} 年级 ${c.name}`, value: c.id })),
)
const gradeOptions = computed(() => {
  const grades = [...new Set(classes.value.map((c) => c.grade))].sort((a, b) => a - b)
  return (grades.length ? grades : [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])
    .map((g) => ({ label: `${g} 年级`, value: g }))
})
const participants = ref<ExamParticipant[]>([])
const studentOptions = computed(() =>
  participants.value.map((p) => ({
    label: `${p.student_name}(${p.student_no}) ${p.class_name ?? ''}`, value: p.student_id,
  })),
)

function goBack() {
  void router.push({ name: 'exam-exam-detail', params: { id: examId } })
}

function doPrint() {
  window.print()
}

async function onExportReportPack() {
  try {
    await downloadReportPack(examId)
    message.success('报表包已开始下载')
  } catch (e) {
    message.error((e as ApiError).detail || '报表包导出失败')
  }
}

// ── 分析设置(KW-41~44 共用) ──
const settings = ref<AnalysisSettings | null>(null)
const settingsForm = ref<{
  rank_tie_rule: RankTieRule
  segment_size: number
  critical_total_line: number | null
  critical_margin: number
  subject_critical_margin: number
}>({
  rank_tie_rule: DEFAULT_ANALYSIS_SETTINGS.rank_tie_rule,
  segment_size: DEFAULT_ANALYSIS_SETTINGS.segment_size,
  critical_total_line: null as number | null,
  critical_margin: DEFAULT_ANALYSIS_SETTINGS.critical_margin,
  subject_critical_margin: DEFAULT_ANALYSIS_SETTINGS.subject_critical_margin,
})
const tieRuleOptions = RANK_TIE_RULES.map((r) => ({ label: RANK_TIE_RULE_LABELS[r], value: r }))
async function reloadSettings() {
  try {
    settings.value = await getAnalysisSettings(examId)
    settingsForm.value = {
      // 后端 rank_tie_rule 为自由字符串,前端只认 dense/competition 两种,其他值由后端兜底。
      rank_tie_rule: settings.value.rank_tie_rule as RankTieRule,
      segment_size: settings.value.segment_size,
      critical_total_line: settings.value.critical_total_line,
      critical_margin: settings.value.critical_margin,
      subject_critical_margin: settings.value.subject_critical_margin,
    }
  } catch (e) {
    message.error((e as ApiError).detail || '分析设置加载失败')
  }
}
async function saveSettings() {
  if (settingsForm.value.segment_size < 1) { message.warning('分段粒度须大于 0'); return }
  try {
    settings.value = await saveAnalysisSettings(examId, {
      rank_tie_rule: settingsForm.value.rank_tie_rule,
      segment_size: settingsForm.value.segment_size,
      critical_total_line: settingsForm.value.critical_total_line,
      critical_margin: settingsForm.value.critical_margin,
      subject_critical_margin: settingsForm.value.subject_critical_margin,
    })
    message.success('分析设置已保存')
    await Promise.all([reloadRankings(), reloadSegments()])
  } catch (e) {
    message.error((e as ApiError).detail || '分析设置保存失败')
  }
}

// ── 科目及格优秀线覆盖(KW-43) ──
interface ThresholdRow { subject_id: number; subject_name: string; pass_line: number | null; excellent_line: number | null }
const thresholdRows = ref<ThresholdRow[]>([])
async function reloadThresholds() {
  try {
    const res = await listSubjectThresholds(examId)
    const bySubject = new Map(res.items.map((t: SubjectThreshold) => [t.subject_id, t]))
    thresholdRows.value = examSubjects.value.map((s) => {
      const t = bySubject.get(s.subject_id)
      return {
        subject_id: s.subject_id, subject_name: s.subject_name,
        pass_line: t?.pass_line ?? null, excellent_line: t?.excellent_line ?? null,
      }
    })
  } catch (e) {
    message.error((e as ApiError).detail || '科目及格优秀线加载失败')
  }
}
async function saveThresholds() {
  try {
    await saveSubjectThresholds(examId, thresholdRows.value.map((r) => ({
      subject_id: r.subject_id, pass_line: r.pass_line, excellent_line: r.excellent_line,
    })))
    message.success('科目及格优秀线已保存')
    await reloadSummary()
  } catch (e) {
    message.error((e as ApiError).detail || '科目及格优秀线保存失败')
  }
}

// ── 等第档(KW-50) ──
interface GradeBandRow { subject_id: number | null; grade_label: string; min_score: number; max_score: number }
const bandSubjectId = ref<number | null>(null)
const bandSubjectOptions = computed(() => [
  // null 表示通用档:编译期按 number 写,运行时仍为 null,后端 subject_id 为 null 即通用。
  { label: '通用(全部科目)', value: null as unknown as number },
  ...subjectOptions.value,
])
const bandRows = ref<GradeBandRow[]>([])
async function reloadGradeBands() {
  try {
    const res = await listGradeBands(examId, bandSubjectId.value)
    bandRows.value = res.items.map((b: GradeBand) => ({
      subject_id: b.subject_id, grade_label: b.grade_label,
      min_score: b.min_score, max_score: b.max_score,
    }))
  } catch (e) {
    message.error((e as ApiError).detail || '等第档加载失败')
  }
}
function addBandRow() {
  bandRows.value.push({ subject_id: bandSubjectId.value, grade_label: '', min_score: 0, max_score: 100 })
}
function removeBandRow(row: GradeBandRow) {
  bandRows.value = bandRows.value.filter((r) => r !== row)
}
async function saveBands() {
  const bad = bandRows.value.find((r) => !r.grade_label.trim() || r.min_score > r.max_score)
  if (bad) { message.warning('等第名称不能为空,且最低分不能高于最高分'); return }
  try {
    await saveGradeBands(examId, bandRows.value.map((r) => ({
      subject_id: r.subject_id, grade_label: r.grade_label.trim(),
      min_score: r.min_score, max_score: r.max_score,
    })))
    message.success('等第档已保存')
    await Promise.all([reloadGradeBands(), reloadGradeDistribution()])
  } catch (e) {
    message.error((e as ApiError).detail || '等第档保存失败')
  }
}

// ── 汇总(KW-41、KW-43) ──
const summaryScope = ref<'grade' | 'class'>('grade')
const scopeOptions: { label: string; value: 'grade' | 'class' }[] = [
  { label: ANALYSIS_SCOPE_LABELS.grade, value: 'grade' },
  { label: ANALYSIS_SCOPE_LABELS.class, value: 'class' },
]
const summaryGrade = ref<number | null>(null)
const summaryClassId = ref<number | null>(null)
const summary = ref<AnalysisSummary | null>(null)
const summaryHint = ref('')
async function reloadSummary() {
  summaryHint.value = ''
  if (summaryScope.value === 'class' && summaryClassId.value == null) {
    summaryHint.value = '请选择班级后查看班级汇总'
    summary.value = null
    return
  }
  try {
    summary.value = await getAnalysisSummary(examId, {
      scope: summaryScope.value,
      grade: summaryGrade.value,
      classUnitId: summaryScope.value === 'class' ? summaryClassId.value : null,
    })
  } catch (e) {
    message.error((e as ApiError).detail || '汇总加载失败')
  }
}

// ── 排名(KW-42) ──
const rankScope = ref<'grade' | 'class'>('grade')
const rankSubjectId = ref<number | null>(null)
const rankGrade = ref<number | null>(null)
const rankClassId = ref<number | null>(null)
const rankings = ref<RankingItem[]>([])
const rankTotal = ref(0)
const rankHint = ref('')
const rankSubjectOptions = computed(() => [
  // null 表示总分:编译期按 number 写,运行时仍为 null,不带 subject_id 即查总分。
  { label: '总分', value: null as unknown as number },
  ...subjectOptions.value,
])
async function reloadRankings() {
  rankHint.value = ''
  if (rankScope.value === 'class' && rankClassId.value == null) {
    rankHint.value = '请选择班级后查看班级排名'
    rankings.value = []
    return
  }
  try {
    const res = await getAnalysisRankings(examId, {
      scope: rankScope.value,
      subjectId: rankSubjectId.value,
      grade: rankGrade.value,
      classUnitId: rankScope.value === 'class' ? rankClassId.value : null,
    })
    rankings.value = res.items
    rankTotal.value = res.total
  } catch (e) {
    message.error((e as ApiError).detail || '排名加载失败')
  }
}
/** 排名并列说明:按当前并列规则,取第一个并列组算下一名次,无并列时只显示规则文案。 */
const rankTieNote = computed(() => {
  const rule = settingsForm.value.rank_tie_rule
  const base = tieRuleHint(rule)
  const tied = tieGroups(rankings.value).find((g) => g.count > 1)
  if (!tied) return base
  return `${base};本次第 ${tied.rank} 名并列 ${tied.count} 人,下一名次为第 ${nextRankAfterTie(rule, tied.rank, tied.count)} 名`
})

// ── 分数段分布(KW-44) ──
const segmentSubjectId = ref<number | null>(null)
const segmentScope = ref<'grade' | 'class'>('grade')
const segmentGrade = ref<number | null>(null)
const segmentClassId = ref<number | null>(null)
const segments = ref<Segment[]>([])
const segmentHint = ref('')
async function reloadSegments() {
  segmentHint.value = ''
  if (segmentScope.value === 'class' && segmentClassId.value == null) {
    segmentHint.value = '请选择班级后查看班级分数段分布'
    segments.value = []
    return
  }
  try {
    const res = await getAnalysisSegments(examId, {
      subjectId: segmentSubjectId.value,
      scope: segmentScope.value,
      grade: segmentGrade.value,
      classUnitId: segmentScope.value === 'class' ? segmentClassId.value : null,
    })
    segments.value = res.segments
  } catch (e) {
    message.error((e as ApiError).detail || '分数段分布加载失败')
  }
}

// ── 临界生(KW-45) ──
const criticalItems = ref<CriticalItem[]>([])
async function reloadCritical() {
  try {
    criticalItems.value = (await getAnalysisCritical(examId)).items
  } catch (e) {
    message.error((e as ApiError).detail || '临界生加载失败')
  }
}

// ── 目标生(KW-46) ──
const targetStudents = ref<TargetStudent[]>([])
const targetTracking = ref<TargetTrackingItem[]>([])
const targetForm = ref({ student_id: null as number | null, target_total: null as number | null, note: '' })
async function reloadTargets() {
  try {
    targetStudents.value = (await listTargetStudents(examId)).items
    targetTracking.value = (await getTargetTracking(examId)).items
  } catch (e) {
    message.error((e as ApiError).detail || '目标生加载失败')
  }
}
async function addTarget() {
  if (!targetForm.value.student_id) { message.warning('请选择学生'); return }
  try {
    await createTargetStudent(examId, {
      student_id: targetForm.value.student_id,
      target_total: targetForm.value.target_total,
      note: targetForm.value.note.trim() || null,
    })
    targetForm.value = { student_id: null, target_total: null, note: '' }
    message.success('已加入目标生')
    await reloadTargets()
  } catch (e) {
    message.error((e as ApiError).detail || '加入目标生失败')
  }
}
async function removeTargetByStudent(studentId: number) {
  const t = targetStudents.value.find((s) => s.student_id === studentId)
  if (t) await removeTarget(t)
}

async function removeTarget(t: TargetStudent) {
  try {
    await deleteTargetStudent(examId, t.id)
    message.success('已移除目标生')
    await reloadTargets()
  } catch (e) {
    message.error((e as ApiError).detail || '移除目标生失败')
  }
}

// ── 进退步分析(KW-47):无上次考试时后端 message 原样展示 ──

// ── 进退步分析(KW-47):无上次考试时后端 message 原样展示 ──
const progress = ref<AnalysisProgress | null>(null)
const progressMessage = computed(() => progress.value ? progressEmptyMessage(progress.value) : null)
async function reloadProgress() {
  try {
    progress.value = await getAnalysisProgress(examId)
  } catch (e) {
    message.error((e as ApiError).detail || '进退步分析加载失败')
  }
}

// ── 学科与班级质量对比(KW-48):仅管理角色可见 ──
// 前端无法从登录角色直接判断年级组长身份(年级组长由教务主任的年级范围派生),
// 因此直接请求,后端 403 时原样展示提示,不假装有权限。
const quality = ref<QualityCompare | null>(null)
const qualityGrade = ref<number | null>(null)
const qualityForbidden = ref('')
async function reloadQuality() {
  qualityForbidden.value = ''
  try {
    quality.value = await getQualityCompare(examId, qualityGrade.value)
  } catch (e) {
    const err = e as ApiError
    if (err.status === 403) {
      quality.value = null
      qualityForbidden.value = err.detail || QUALITY_COMPARE_FORBIDDEN_HINT
    } else {
      message.error(err.detail || '质量对比加载失败')
    }
  }
}

// ── 学生个人成绩趋势(KW-49):表格展示历次考试,不画复杂图表 ──
const trendStudentId = ref<number | null>(null)
const trend = ref<StudentTrend | null>(null)
const trendSubjectNames = computed(() => {
  const names = new Set<string>()
  for (const ex of trend.value?.exams ?? []) {
    for (const k of Object.keys(ex.subjects ?? {})) names.add(k)
  }
  return [...names]
})
async function reloadTrend() {
  if (!trendStudentId.value) { trend.value = null; return }
  try {
    trend.value = await getStudentTrend(examId, trendStudentId.value)
  } catch (e) {
    message.error((e as ApiError).detail || '个人成绩趋势加载失败')
  }
}

// ── 等第分布(KW-50) ──
const distSubjectId = ref<number | null>(null)
const distBands = ref<GradeDistributionBand[]>([])
async function reloadGradeDistribution() {
  try {
    distBands.value = (await getGradeDistribution(examId, distSubjectId.value)).bands
  } catch (e) {
    message.error((e as ApiError).detail || '等第分布加载失败')
  }
}

async function reloadAll() {
  loading.value = true
  forbidden.value = false
  try {
    const exam = await getExam(examId)
    examName.value = exam.name
    semesterId.value = exam.semester_id
    examSubjects.value = (exam.subjects ?? []).map((s) => ({
      subject_id: s.subject_id, subject_name: s.subject_name, full_score: s.full_score,
    }))
    const [classList, plist] = await Promise.all([
      listClassUnits(exam.semester_id),
      listParticipants(examId),
    ])
    classes.value = classList
    participants.value = plist.items
    await Promise.all([
      reloadSettings(), reloadThresholds(), reloadGradeBands(), reloadSummary(),
      reloadRankings(), reloadSegments(), reloadCritical(), reloadTargets(),
      reloadProgress(), reloadQuality(), reloadGradeDistribution(),
    ])
  } catch (e) {
    if ((e as ApiError).status === 403) forbidden.value = true
    else message.error((e as ApiError).detail || '加载失败')
  } finally {
    loading.value = false
  }
}
onMounted(() => { void reloadAll() })
</script>

<template>
  <div class="ios-page">
    <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap">
      <n-button text type="primary" @click="goBack">← 考试详情</n-button>
      <h1 class="ios-title">{{ examName ? `${examName} · 成绩分析` : '成绩分析' }}</h1>
      <n-space :wrap="true" style="margin-left: auto" class="no-print">
        <n-button data-testid="analysis-print-btn" @click="doPrint">打印</n-button>
        <n-button type="primary" data-testid="analysis-export-report-pack" @click="onExportReportPack">导出报表包(Excel)</n-button>
      </n-space>
    </div>
    <n-text depth="3" style="font-size: 12px; display: block; margin-top: 6px">
      报表包为 Excel 多表(年级汇总、班级对比、学科分析、临界生、目标生);如需 PDF,请用上方“打印”按钮,在浏览器打印对话框选“另存为 PDF”。
    </n-text>

    <n-alert v-if="forbidden" type="error" style="margin-top: 16px">
      无权查看该考试(不在你的可见范围内)。
    </n-alert>
    <n-empty v-else-if="!loading && !examName" description="找不到该考试" style="margin-top: 24px" />

    <template v-else-if="examName">
      <!-- 分析设置(KW-41~44 共用) -->
      <div class="ios-section">
        <div class="ios-section-title">分析设置</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            排名并列规则、临界线与浮动分值、及格/优秀线、等第划分规则等口径待学校确认;此处只保存学校定好的口径,不替学校定口径。
          </n-text>
          <n-space :wrap="true" align="center">
            <n-text>排名并列规则</n-text>
            <n-select
              v-model:value="settingsForm.rank_tie_rule" :options="tieRuleOptions"
              :disabled="!canManage" style="width: 170px"
            />
            <n-text>分段粒度(分)</n-text>
            <n-input-number v-model:value="settingsForm.segment_size" :min="1" :disabled="!canManage" style="width: 100px" />
            <n-text>总分临界线(空为不设)</n-text>
            <n-input-number v-model:value="settingsForm.critical_total_line" :min="0" clearable :disabled="!canManage" style="width: 110px" />
            <n-text>总分临界浮动(分)</n-text>
            <n-input-number v-model:value="settingsForm.critical_margin" :min="0" :disabled="!canManage" style="width: 90px" />
            <n-text>单科临界浮动(分)</n-text>
            <n-input-number v-model:value="settingsForm.subject_critical_margin" :min="0" :disabled="!canManage" style="width: 90px" />
            <n-button v-if="canManage" type="primary" @click="saveSettings">保存设置</n-button>
          </n-space>
          <n-text depth="3" style="font-size: 12px; display: block; margin-top: 8px" data-testid="analysis-tie-rule-hint">
            {{ tieRuleHint(settingsForm.rank_tie_rule) }}
          </n-text>
        </div></div>
      </div>

      <!-- 科目及格优秀线覆盖(KW-43) -->
      <div class="ios-section">
        <div class="ios-section-title">科目及格优秀线</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            覆盖本次考试单科的及格线与优秀线;留空则用学科分值设置里的线。及格率、优秀率、低分率按覆盖后的线统计。
          </n-text>
          <table class="ios-table">
            <thead><tr><th>科目</th><th>及格线</th><th>优秀线</th></tr></thead>
            <tbody>
              <tr v-for="r in thresholdRows" :key="r.subject_id">
                <td>{{ r.subject_name }}</td>
                <td><n-input-number v-model:value="r.pass_line" :min="0" clearable :disabled="!canManage" style="width: 110px" /></td>
                <td><n-input-number v-model:value="r.excellent_line" :min="0" clearable :disabled="!canManage" style="width: 110px" /></td>
              </tr>
            </tbody>
          </table>
          <n-empty v-if="thresholdRows.length === 0" description="本次考试尚未编排科目" />
          <n-button v-if="canManage && thresholdRows.length" type="primary" style="margin-top: 12px" @click="saveThresholds">保存及格优秀线</n-button>
        </div></div>
      </div>

      <!-- 等第档(KW-50) -->
      <div class="ios-section">
        <div class="ios-section-title">等第档</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            按分数线划分等第(如 A/B/C/D 或合格/不合格);“通用”档用于全部科目,也可按科目另设档。等第划分规则(比例还是分数线)待学校提供。
          </n-text>
          <n-space :wrap="true" align="center" style="margin-bottom: 12px">
            <n-text>适用科目</n-text>
            <n-select
              v-model:value="bandSubjectId" :options="bandSubjectOptions" style="width: 180px"
              @update:value="reloadGradeBands"
            />
            <n-button v-if="canManage" @click="addBandRow">新增一档</n-button>
          </n-space>
          <table class="ios-table">
            <thead><tr><th>等第</th><th>最低分</th><th>最高分</th><th /></tr></thead>
            <tbody>
              <tr v-for="r in bandRows" :key="`${r.grade_label}-${r.min_score}-${r.max_score}`">
                <td><n-input v-model:value="r.grade_label" placeholder="如 A" :disabled="!canManage" style="width: 100px" /></td>
                <td><n-input-number v-model:value="r.min_score" :disabled="!canManage" style="width: 110px" /></td>
                <td><n-input-number v-model:value="r.max_score" :disabled="!canManage" style="width: 110px" /></td>
                <td><n-button v-if="canManage" size="small" text type="error" @click="removeBandRow(r)">移除</n-button></td>
              </tr>
            </tbody>
          </table>
          <n-empty v-if="bandRows.length === 0" description="暂无等第档,请新增" />
          <n-button v-if="canManage && bandRows.length" type="primary" style="margin-top: 12px" @click="saveBands">保存等第档</n-button>
        </div></div>
      </div>

      <!-- 汇总(KW-41、KW-43) -->
      <div class="ios-section">
        <div class="ios-section-title">汇总</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-space :wrap="true" align="center">
            <n-select
              v-model:value="summaryScope" :options="scopeOptions"
              style="width: 110px" @update:value="reloadSummary"
            />
            <n-select
              v-model:value="summaryGrade" :options="gradeOptions" clearable placeholder="年级"
              style="width: 120px" @update:value="reloadSummary"
            />
            <n-select
              v-if="summaryScope === 'class'" v-model:value="summaryClassId" :options="classOptions"
              clearable placeholder="班级" style="width: 180px" @update:value="reloadSummary"
            />
          </n-space>
          <n-alert v-if="summaryHint" type="info" style="margin-top: 12px">{{ summaryHint }}</n-alert>
          <template v-if="summary">
            <n-text style="font-size: 13px; display: block; margin-top: 12px" data-testid="analysis-summary-totals">
              总分:共 {{ summary.totals.count }} 人,均分 {{ formatScore(summary.totals.avg) }},
              最高 {{ formatScore(summary.totals.max) }},最低 {{ formatScore(summary.totals.min) }},
              标准差 {{ formatScore(summary.totals.std) }}
            </n-text>
            <table class="ios-table" style="margin-top: 8px">
              <thead><tr><th>科目</th><th>人数</th><th>均分</th><th>最高</th><th>最低</th><th>标准差</th><th>及格率</th><th>优秀率</th><th>低分率</th></tr></thead>
              <tbody>
                <tr v-for="s in summary.subjects" :key="s.subject_id">
                  <td>{{ s.subject_name }}</td>
                  <td>{{ s.count }}</td>
                  <td>{{ formatScore(s.avg) }}</td>
                  <td>{{ formatScore(s.max) }}</td>
                  <td>{{ formatScore(s.min) }}</td>
                  <td>{{ formatScore(s.std) }}</td>
                  <td>{{ formatPct(s.pass_rate) }}</td>
                  <td>{{ formatPct(s.excellent_rate) }}</td>
                  <td>{{ formatPct(s.low_rate) }}</td>
                </tr>
              </tbody>
            </table>
            <n-empty v-if="summary.subjects.length === 0" description="暂无科目汇总" />
          </template>
        </div></div>
      </div>

      <!-- 排名(KW-42) -->
      <div class="ios-section">
        <div class="ios-section-title">排名</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-space :wrap="true" align="center">
            <n-select
              v-model:value="rankScope" :options="scopeOptions"
              style="width: 110px" @update:value="reloadRankings"
            />
            <n-select
              v-model:value="rankSubjectId" :options="rankSubjectOptions" style="width: 130px"
              @update:value="reloadRankings"
            />
            <n-select
              v-model:value="rankGrade" :options="gradeOptions" clearable placeholder="年级"
              style="width: 120px" @update:value="reloadRankings"
            />
            <n-select
              v-if="rankScope === 'class'" v-model:value="rankClassId" :options="classOptions"
              clearable placeholder="班级" style="width: 180px" @update:value="reloadRankings"
            />
          </n-space>
          <n-text depth="3" style="font-size: 12px; display: block; margin-top: 8px" data-testid="analysis-rank-tie-note">
            {{ rankTieNote }}
          </n-text>
          <n-alert v-if="rankHint" type="info" style="margin-top: 12px">{{ rankHint }}</n-alert>
          <table class="ios-table" style="margin-top: 8px">
            <thead><tr><th>名次</th><th>学号</th><th>姓名</th><th>班级</th><th>总分</th><th /></tr></thead>
            <tbody>
              <tr v-for="r in rankings" :key="r.student_id">
                <td>{{ r.rank }}</td>
                <td>{{ r.student_no }}</td>
                <td>{{ r.student_name }}</td>
                <td>{{ r.class_name }}</td>
                <td>{{ formatScore(r.total) }}</td>
                <td>
                  <n-text v-if="tieGroups(rankings).some((g) => g.rank === r.rank && g.count > 1)" depth="3" style="font-size: 12px">并列</n-text>
                </td>
              </tr>
            </tbody>
          </table>
          <n-empty v-if="rankings.length === 0 && !rankHint" description="暂无排名" />
          <n-text depth="3" style="font-size: 13px">共 {{ rankTotal }} 人</n-text>
        </div></div>
      </div>

      <!-- 分数段分布(KW-44) -->
      <div class="ios-section">
        <div class="ios-section-title">分数段分布</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-space :wrap="true" align="center">
            <n-select
              v-model:value="segmentSubjectId" :options="rankSubjectOptions" style="width: 130px"
              @update:value="reloadSegments"
            />
            <n-select
              v-model:value="segmentScope" :options="scopeOptions"
              style="width: 110px" @update:value="reloadSegments"
            />
            <n-select
              v-model:value="segmentGrade" :options="gradeOptions" clearable placeholder="年级"
              style="width: 120px" @update:value="reloadSegments"
            />
            <n-select
              v-if="segmentScope === 'class'" v-model:value="segmentClassId" :options="classOptions"
              clearable placeholder="班级" style="width: 180px" @update:value="reloadSegments"
            />
            <n-text depth="3" style="font-size: 12px">分段粒度 {{ settingsForm.segment_size }} 分(见分析设置)</n-text>
          </n-space>
          <n-alert v-if="segmentHint" type="info" style="margin-top: 12px">{{ segmentHint }}</n-alert>
          <table class="ios-table" style="margin-top: 8px">
            <thead><tr><th>分数段</th><th>人数</th><th>占比</th></tr></thead>
            <tbody>
              <tr v-for="s in segments" :key="s.label">
                <td>{{ s.label }}</td>
                <td>{{ s.count }}</td>
                <td>{{ formatPct(s.pct) }}</td>
              </tr>
            </tbody>
          </table>
          <n-empty v-if="segments.length === 0 && !segmentHint" description="暂无分数段分布" />
        </div></div>
      </div>

      <!-- 临界生(KW-45) -->
      <div class="ios-section">
        <div class="ios-section-title">临界生</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            总分临界线 {{ settingsForm.critical_total_line ?? '未设' }} 上下 {{ settingsForm.critical_margin }} 分、
            单科及格线上下 {{ settingsForm.subject_critical_margin }} 分范围内的学生;临界线由学校提供,无官方线时用校内自定线。
          </n-text>
          <table class="ios-table">
            <thead><tr><th>学号</th><th>姓名</th><th>班级</th><th>总分</th><th>距临界线</th><th>单科临界</th></tr></thead>
            <tbody>
              <tr v-for="c in criticalItems" :key="c.student_id">
                <td>{{ c.student_no }}</td>
                <td>{{ c.student_name }}</td>
                <td>{{ c.class_name }}</td>
                <td>{{ formatScore(c.total) }}</td>
                <td>{{ formatScore(c.gap_to_line) }}</td>
                <td>
                  <span v-if="c.subject_gaps.length === 0">—</span>
                  <span v-for="g in c.subject_gaps" :key="g.subject_name" style="display: block">
                    {{ g.subject_name }} {{ formatScore(g.score) }}(距线 {{ formatScore(g.gap) }})
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
          <n-empty v-if="criticalItems.length === 0" description="暂无临界生" />
        </div></div>
      </div>

      <!-- 目标生跟踪(KW-46) -->
      <div class="ios-section">
        <div class="ios-section-title">目标生跟踪</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            目标生名单与目标线由学校提供,系统只做跟踪对比:是否达标、各科短板科目。
          </n-text>
          <n-space v-if="canManage" :wrap="true" align="center" style="margin-bottom: 12px" class="no-print">
            <n-select
              v-model:value="targetForm.student_id" :options="studentOptions" filterable
              placeholder="按姓名或学号选择学生" style="width: 240px"
            />
            <n-input-number v-model:value="targetForm.target_total" :min="0" clearable placeholder="目标总分" style="width: 120px" />
            <n-input v-model:value="targetForm.note" placeholder="备注(选填)" style="width: 180px" />
            <n-button type="primary" @click="addTarget">加入目标生</n-button>
          </n-space>
          <table class="ios-table">
            <thead><tr><th>学号</th><th>姓名</th><th>班级</th><th>目标总分</th><th>本次总分</th><th>是否达标</th><th>短板科目</th><th>备注</th><th /></tr></thead>
            <tbody>
              <tr v-for="t in targetTracking" :key="t.student_id">
                <td>{{ t.student_no }}</td>
                <td>{{ t.student_name }}</td>
                <td>{{ t.class_name }}</td>
                <td>{{ formatScore(t.target_total) }}</td>
                <td>{{ formatScore(t.total) }}</td>
                <td>{{ t.reached ? '已达标' : '未达标' }}</td>
                <td>{{ t.weak_subjects.length ? t.weak_subjects.join('、') : '—' }}</td>
                <td>{{ targetStudents.find((s) => s.student_id === t.student_id)?.note ?? '—' }}</td>
                <td>
                  <n-popconfirm
                    v-if="canManage"
                    @positive-click="removeTargetByStudent(t.student_id)"
                  >
                    <template #trigger><n-button size="small" text type="error">移除</n-button></template>
                    确定移除该目标生?
                  </n-popconfirm>
                </td>
              </tr>
            </tbody>
          </table>
          <n-empty v-if="targetTracking.length === 0" description="暂无目标生" />
        </div></div>
      </div>

      <!-- 进退步分析(KW-47) -->
      <div class="ios-section">
        <div class="ios-section-title">进退步分析</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            与上一次同类考试对比,计算每名学生名次进退步;对比基准默认上一次同类型考试,是否可比待学校确认。
          </n-text>
          <n-alert
            v-if="progressMessage" type="info" style="margin-bottom: 12px"
            data-testid="analysis-progress-empty"
          >{{ progressMessage }}</n-alert>
          <template v-if="progress && progress.items.length > 0">
            <n-text style="font-size: 13px; display: block; margin-bottom: 8px" data-testid="analysis-progress-top">
              进步最大: {{ progress.top_improved.map((p) => `${p.student_name}(进 ${p.delta ?? '—'} 名)`).join('、') || '—' }}
              ;退步最大: {{ progress.top_declined.map((p) => `${p.student_name}(退 ${p.delta ? -p.delta : '—'} 名)`).join('、') || '—' }}
            </n-text>
            <table class="ios-table">
              <thead><tr><th>学号</th><th>姓名</th><th>班级</th><th>上次总分</th><th>本次总分</th><th>上次名次</th><th>本次名次</th><th>进退步(名)</th></tr></thead>
              <tbody>
                <tr v-for="p in progress.items" :key="p.student_id">
                  <td>{{ p.student_no }}</td>
                  <td>{{ p.student_name }}</td>
                  <td>{{ p.class_name }}</td>
                  <td>{{ formatScore(p.prev_total) }}</td>
                  <td>{{ formatScore(p.total) }}</td>
                  <td>{{ p.prev_rank ?? '—' }}</td>
                  <td>{{ p.rank ?? '—' }}</td>
                  <td>{{ p.delta == null ? '—' : (p.delta > 0 ? `进 ${p.delta}` : p.delta < 0 ? `退 ${-p.delta}` : '持平') }}</td>
                </tr>
              </tbody>
            </table>
          </template>
        </div></div>
      </div>

      <!-- 学科与班级质量对比(KW-48) -->
      <div class="ios-section">
        <div class="ios-section-title">学科与班级质量对比</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            涉及教师教学评价,仅对管理角色开放,查看权限严格限定,避免扩散。
          </n-text>
          <n-space :wrap="true" align="center" style="margin-bottom: 12px">
            <n-select
              v-model:value="qualityGrade" :options="gradeOptions" clearable placeholder="年级(全部)"
              style="width: 140px" @update:value="reloadQuality"
            />
          </n-space>
          <n-alert
            v-if="qualityForbidden" type="warning" data-testid="analysis-quality-forbidden"
          >{{ qualityForbidden }}</n-alert>
          <template v-if="quality">
            <n-text style="font-size: 13px; display: block; margin-bottom: 6px">按学科对比各班</n-text>
            <div v-for="s in quality.subjects" :key="s.subject_id" style="margin-bottom: 12px">
              <n-text strong style="font-size: 13px">{{ s.subject_name }}</n-text>
              <table class="ios-table">
                <thead><tr><th>班级</th><th>均分</th><th>及格率</th><th>优秀率</th></tr></thead>
                <tbody>
                  <tr v-for="c in s.classes" :key="c.class_unit_id">
                    <td>{{ c.class_name }}</td>
                    <td>{{ formatScore(c.avg) }}</td>
                    <td>{{ formatPct(c.pass_rate) }}</td>
                    <td>{{ formatPct(c.excellent_rate) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <n-text style="font-size: 13px; display: block; margin-bottom: 6px">按班级对比各科</n-text>
            <div v-for="c in quality.classes" :key="c.class_unit_id" style="margin-bottom: 12px">
              <n-text strong style="font-size: 13px">{{ c.class_name }}</n-text>
              <table class="ios-table">
                <thead><tr><th>科目</th><th>均分</th><th>及格率</th></tr></thead>
                <tbody>
                  <tr v-for="s in c.subjects" :key="s.subject_id">
                    <td>{{ s.subject_name }}</td>
                    <td>{{ formatScore(s.avg) }}</td>
                    <td>{{ formatPct(s.pass_rate) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <n-empty v-if="quality.subjects.length === 0 && quality.classes.length === 0" description="暂无质量对比数据" />
          </template>
        </div></div>
      </div>

      <!-- 学生个人成绩趋势(KW-49) -->
      <div class="ios-section">
        <div class="ios-section-title">学生个人成绩趋势</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            选一名学生,看历次考试总分与各科走势,供班主任面谈使用;用表格展示,不画复杂图表。
          </n-text>
          <n-space :wrap="true" align="center" style="margin-bottom: 12px">
            <n-select
              v-model:value="trendStudentId" :options="studentOptions" filterable clearable
              placeholder="按姓名或学号选择学生" style="width: 240px" @update:value="reloadTrend"
            />
          </n-space>
          <template v-if="trend">
            <n-text strong style="font-size: 13px; display: block; margin-bottom: 6px">{{ trend.student_name }} · 历次考试</n-text>
            <table class="ios-table">
              <thead><tr><th>考试</th><th>考试日期</th><th>总分</th><th v-for="n in trendSubjectNames" :key="n">{{ n }}</th></tr></thead>
              <tbody>
                <tr v-for="ex in trend.exams" :key="ex.exam_id">
                  <td>{{ ex.exam_name }}</td>
                  <td>{{ ex.exam_date ?? '—' }}</td>
                  <td>{{ formatScore(ex.total) }}</td>
                  <td v-for="n in trendSubjectNames" :key="n">{{ formatScore(ex.subjects[n]) }}</td>
                </tr>
              </tbody>
            </table>
            <n-empty v-if="trend.exams.length === 0" description="该学生暂无历次考试记录" />
          </template>
        </div></div>
      </div>

      <!-- 等第分布(KW-50) -->
      <div class="ios-section">
        <div class="ios-section-title">等第分布</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-space :wrap="true" align="center" style="margin-bottom: 12px">
            <n-select
              v-model:value="distSubjectId" :options="rankSubjectOptions" style="width: 130px"
              @update:value="reloadGradeDistribution"
            />
            <n-text depth="3" style="font-size: 12px">按等第档统计各等第人数与占比</n-text>
          </n-space>
          <table class="ios-table">
            <thead><tr><th>等第</th><th>人数</th><th>占比</th></tr></thead>
            <tbody>
              <tr v-for="b in distBands" :key="b.grade_label">
                <td>{{ b.grade_label }}</td>
                <td>{{ b.count }}</td>
                <td>{{ formatPct(b.pct) }}</td>
              </tr>
            </tbody>
          </table>
          <n-empty v-if="distBands.length === 0" description="暂无等第分布,请先设置等第档" />
        </div></div>
      </div>

      <!-- 报表包导出(KW-51) -->
      <div class="ios-section">
        <div class="ios-section-title">报表包导出</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            一键导出质量分析会材料包 Excel(年级汇总表、班级对比表、学科分析表、临界生与目标生名单)。
            报表包内容清单可按学校分析会习惯调整。如需 PDF,请用页顶“打印”按钮,在浏览器打印对话框选“另存为 PDF”。
          </n-text>
          <n-space :wrap="true" class="no-print">
            <n-button type="primary" data-testid="analysis-export-report-pack-2" @click="onExportReportPack">导出报表包(Excel)</n-button>
            <n-button data-testid="analysis-print-btn-2" @click="doPrint">打印 / 另存为 PDF</n-button>
          </n-space>
        </div></div>
      </div>
    </template>
  </div>
</template>

<style scoped>
@media print {
  .no-print {
    display: none !important;
  }
}
</style>
