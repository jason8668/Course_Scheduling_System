<script setup lang="ts">
import {
  NAlert, NButton, NDataTable, NEmpty, NInput, NInputNumber, NPopconfirm, NSelect,
  NSpace, NSwitch, NText, useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { computed, h, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import {
  CHEATING_SCORE_MODE_LABELS, CHEATING_SCORE_MODES, ENTRY_MODE_LABELS, ENTRY_MODES,
  MAKEUP_MODE_LABELS, MAKEUP_MODES, MAKEUP_SCORE_STATUSES, MARKING_ROLES,
  MARKING_SCOPE_TYPES, SCORE_STATUSES,
  createMakeup, createMarkingAssignment, createScoreItem, deleteMakeup,
  deleteMarkingAssignment, deleteScoreItem, downloadScoreTemplate, formatImportErrors,
  getExam, getScoreProgress, getScoreSettings, importScores, itemizedTotal,
  listMakeupScores, listMakeups, listMarkingAssignments, listScoreItems, listScores,
  saveMakeupScores, saveScoreSettings, saveScores, submitScores, validateItemValue,
  validateScore,
} from '@/api/exam'
import type {
  Makeup, MakeupScore, MarkingAssignment, ScoreImportResult, ScoreItem,
  ScoreProgress, ScoreRecord, ScoreSettings,
} from '@/api/exam'
import { listClassUnits, listTeachers } from '@/api/basedata'
import type { ClassUnit, Teacher } from '@/api/basedata'
import { classLabel } from '@/utils/labels'
import { useAuthStore } from '@/stores/auth'

const message = useMessage()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const examId = Number(route.params.id)
// 成绩设置与阅卷分工、补考场次只限 admin/director 写,越权时后端回 403,前端原样展示;
// 成绩录入任课教师只限本人所教班级+本科目,越权同样由后端 403 拦截。
const canManage = computed(() => auth.hasRole('admin') || auth.hasRole('director'))

const examName = ref('')
const semesterId = ref(0)
const loading = ref(false)
const forbidden = ref(false)

// 科目取自考试日程(ExamDetail.subjects):满分优先取本次考试该科 full_score,未设取 100,
// 与后端 full_score_for(考试满分→科目分值设置→100)一致,前端满分只用于即时提示。
const examSubjects = ref<{ subject_id: number; subject_name: string; full_score: number | null }[]>([])
const subjectOptions = computed(() =>
  examSubjects.value.map((s) => ({ label: s.subject_name, value: s.subject_id })),
)
function fullScoreFor(subjectId: number | null): number {
  const s = examSubjects.value.find((x) => x.subject_id === subjectId)
  return s?.full_score ?? 100
}
const teachers = ref<Teacher[]>([])
const teacherOptions = computed(() =>
  teachers.value.map((t) => ({ label: t.name, value: t.id })),
)
const classes = ref<ClassUnit[]>([])
const classOptions = computed(() =>
  classes.value.map((c) => ({ label: classLabel(c), value: c.id })),
)

// ── 成绩设置(KW-30) ──
const settings = ref<ScoreSettings | null>(null)
const settingsForm = ref({
  entry_mode: 'total_only',
  makeup_mode: 'separate',
  cheating_score_mode: 'zero',
  absent_counts: false,
  score_deadline: '',
})
const entryModeOptions = ENTRY_MODES.map((m) => ({ label: ENTRY_MODE_LABELS[m], value: m }))
const makeupModeOptions = MAKEUP_MODES.map((m) => ({ label: MAKEUP_MODE_LABELS[m], value: m }))
const cheatingModeOptions = CHEATING_SCORE_MODES.map((m) => ({
  label: CHEATING_SCORE_MODE_LABELS[m], value: m,
}))
async function reloadSettings() {
  try {
    settings.value = await getScoreSettings(examId)
    settingsForm.value = {
      entry_mode: settings.value.entry_mode,
      makeup_mode: settings.value.makeup_mode,
      cheating_score_mode: settings.value.cheating_score_mode,
      absent_counts: settings.value.absent_counts,
      score_deadline: settings.value.score_deadline
        ? settings.value.score_deadline.slice(0, 16) : '',
    }
  } catch (e) {
    message.error((e as ApiError).detail || '成绩设置加载失败')
  }
}
async function saveSettings() {
  try {
    settings.value = await saveScoreSettings(examId, {
      entry_mode: settingsForm.value.entry_mode,
      makeup_mode: settingsForm.value.makeup_mode,
      cheating_score_mode: settingsForm.value.cheating_score_mode,
      absent_counts: settingsForm.value.absent_counts,
      score_deadline: settingsForm.value.score_deadline || null,
    })
    message.success('成绩设置已保存')
    await reloadScores()
  } catch (e) {
    message.error((e as ApiError).detail || '成绩设置保存失败')
  }
}

// ── 阅卷分工(KW-30)与大题小分(KW-31) ──
const markingSubjectId = ref<number | null>(null)
const markingItems = ref<MarkingAssignment[]>([])
const markingForm = ref({
  teacher_id: null as number | null,
  role: '阅卷教师',
  scope_type: '按班',
  scope_value: '',
})
const roleOptions = MARKING_ROLES.map((r) => ({ label: r, value: r }))
const scopeTypeOptions = MARKING_SCOPE_TYPES.map((t) => ({ label: t, value: t }))
async function reloadMarking() {
  try {
    markingItems.value = (
      await listMarkingAssignments(examId, markingSubjectId.value)
    ).items
  } catch (e) {
    message.error((e as ApiError).detail || '阅卷分工加载失败')
  }
}
async function addMarking() {
  if (!markingSubjectId.value) { message.warning('请先选择科目'); return }
  if (!markingForm.value.teacher_id) { message.warning('请选择教师'); return }
  try {
    await createMarkingAssignment(examId, {
      subject_id: markingSubjectId.value,
      teacher_id: markingForm.value.teacher_id,
      role: markingForm.value.role,
      scope_type: markingForm.value.scope_type,
      scope_value: markingForm.value.scope_value.trim() || null,
    })
    message.success('阅卷分工已登记')
    markingForm.value.scope_value = ''
    await reloadMarking()
  } catch (e) {
    message.error((e as ApiError).detail || '阅卷分工登记失败')
  }
}
async function removeMarking(m: MarkingAssignment) {
  try {
    await deleteMarkingAssignment(examId, m.id)
    message.success('已删除')
    await reloadMarking()
  } catch (e) {
    message.error((e as ApiError).detail || '删除失败')
  }
}
const markingColumns: DataTableColumns<MarkingAssignment> = [
  { title: '科目', key: 'subject_name', width: 90 },
  { title: '教师', key: 'teacher_name', width: 90 },
  { title: '角色', key: 'role', width: 90 },
  { title: '分工方式', key: 'scope_type', width: 80 },
  { title: '分工范围', key: 'scope_value', render: (row) => row.scope_value ?? '—' },
  {
    title: '操作', key: 'actions', width: 80,
    render: (row) => canManage.value
      ? h(NPopconfirm, { onPositiveClick: () => removeMarking(row) }, {
        trigger: () => h(NButton, { size: 'small', text: true, type: 'error' }, () => '删除'),
        default: () => '确定删除这条阅卷分工?',
      })
      : h(NText, { depth: 3 }, () => '—'),
  },
]

const scoreItems = ref<ScoreItem[]>([])
const itemForm = ref({ name: '', max_score: null as number | null })
async function reloadScoreItems() {
  if (settingsForm.value.entry_mode !== 'itemized' || !markingSubjectId.value) {
    scoreItems.value = []
    return
  }
  try {
    scoreItems.value = (await listScoreItems(examId, markingSubjectId.value)).items
  } catch (e) {
    message.error((e as ApiError).detail || '大题小分加载失败')
  }
}
async function addScoreItem() {
  if (!markingSubjectId.value) { message.warning('请先选择科目'); return }
  if (!itemForm.value.name.trim()) { message.warning('请输入大题名称'); return }
  if (itemForm.value.max_score == null || itemForm.value.max_score <= 0) {
    message.warning('请填写大于 0 的大题满分'); return
  }
  try {
    await createScoreItem(examId, {
      subject_id: markingSubjectId.value,
      name: itemForm.value.name.trim(),
      max_score: itemForm.value.max_score,
    })
    message.success('大题已添加')
    itemForm.value = { name: '', max_score: null }
    await reloadScoreItems()
  } catch (e) {
    message.error((e as ApiError).detail || '大题添加失败')
  }
}
async function removeScoreItem(item: ScoreItem) {
  try {
    await deleteScoreItem(examId, item.id)
    message.success('已删除')
    await reloadScoreItems()
  } catch (e) {
    message.error((e as ApiError).detail || '删除失败')
  }
}

// ── 成绩录入(KW-31、KW-33) ──
interface DraftRow {
  student_id: number
  student_no: string
  student_name: string
  class_name: string
  grade: number | null
  submitted: boolean
  score: number | null
  status: string
  items: Record<number, number | null>
}
const entrySubjectId = ref<number | null>(null)
const entryClassId = ref<number | null>(null)
const entryStatus = ref<string | null>(null)
const entryQ = ref('')
const statusOptions = SCORE_STATUSES.map((s) => ({ label: s, value: s }))
const rows = ref<DraftRow[]>([])
const scoresLoading = ref(false)
const scoreInputs = ref<(HTMLInputElement | null)[]>([])
function setScoreInputEl(index: number) {
  return (el: unknown) => { scoreInputs.value[index] = el as HTMLInputElement | null }
}
function focusNextRow(index: number) {
  const next = scoreInputs.value[index + 1]
  if (next) next.focus()
}
function entryItemsFor(subjectId: number | null): ScoreItem[] {
  // 大题小分按“阅卷分工区所选科目”维护;录入科目与之一致时直接用,避免多一次请求。
  return subjectId != null && subjectId === markingSubjectId.value ? scoreItems.value : []
}
function rowError(row: DraftRow): string | null {
  if (row.status !== '正常') return null
  const full = fullScoreFor(entrySubjectId.value)
  if (settingsForm.value.entry_mode === 'itemized') {
    const items = entryItemsFor(entrySubjectId.value)
    for (const it of items) {
      const err = validateItemValue(row.items[it.id], it)
      if (err) return err
    }
    const total = itemizedTotal(items.map((it) => row.items[it.id]))
    return validateScore(total, full)
  }
  return validateScore(row.score, full)
}
const hasRowError = computed(() => rows.value.some((r) => rowError(r) !== null))
const enteredCount = computed(() =>
  rows.value.filter((r) => r.score !== null || r.status !== '正常').length,
)
/** 作弊/缺考/免考不填分数,按设置折算展示:作弊记 0 分或记空,缺考与免考记空。 */
function effectiveScoreText(row: DraftRow): string {
  if (row.status === '作弊') {
    return settingsForm.value.cheating_score_mode === 'zero' ? '0 分' : '取消成绩'
  }
  return '—'
}
async function reloadScores() {
  if (!entrySubjectId.value) { rows.value = []; return }
  scoresLoading.value = true
  try {
    const res = await listScores(examId, {
      subjectId: entrySubjectId.value,
      classUnitId: entryClassId.value,
      status: entryStatus.value,
      q: entryQ.value || undefined,
    })
    rows.value = res.items.map((r: ScoreRecord) => {
      const items: Record<number, number | null> = {}
      for (const iv of r.items ?? []) items[iv.item_id] = iv.value
      return {
        student_id: r.student_id, student_no: r.student_no, student_name: r.student_name,
        class_name: r.class_name, grade: r.grade, submitted: r.submitted,
        score: r.score, status: r.status || '正常', items,
      }
    })
  } catch (e) {
    message.error((e as ApiError).detail || '成绩加载失败')
  } finally {
    scoresLoading.value = false
  }
}
async function saveEntryScores() {
  if (!entrySubjectId.value) { message.warning('请先选择科目'); return }
  if (hasRowError.value) { message.error('存在超满分或小分超限的成绩,请先修正再保存'); return }
  const isItemized = settingsForm.value.entry_mode === 'itemized'
  const items = entryItemsFor(entrySubjectId.value)
  // 只发有内容的行:分数、非正常状态或小分任一有值;全空行不发,避免后端建空成绩行。
  const payload = rows.value
    .filter((r) => {
      if (r.score !== null || r.status !== '正常') return true
      return items.some((it) => r.items[it.id] !== null && r.items[it.id] !== undefined)
    })
    .map((r) => {
      if (isItemized && r.status === '正常') {
        const vals = items
          .filter((it) => r.items[it.id] !== null && r.items[it.id] !== undefined)
          .map((it) => ({ item_id: it.id, value: r.items[it.id] as number }))
        return {
          student_id: r.student_id, score: itemizedTotal(vals.map((v) => v.value)),
          status: r.status, items: vals,
        }
      }
      return {
        student_id: r.student_id,
        score: r.status === '正常' ? r.score : null,
        status: r.status,
      }
    })
  if (!payload.length) { message.warning('没有可保存的成绩'); return }
  try {
    const res = await saveScores(examId, entrySubjectId.value, payload)
    message.success(`已保存 ${res.updated} 人成绩`)
    await reloadScores()
    await reloadProgress()
  } catch (e) {
    // 超满分后端回 422,前端原样展示,不改写。
    message.error((e as ApiError).detail || '保存失败')
  }
}
async function submitEntryScores() {
  if (!entrySubjectId.value) { message.warning('请先选择科目'); return }
  if (hasRowError.value) { message.error('存在超满分或小分超限的成绩,请先修正再提交'); return }
  try {
    const res = await submitScores(examId, entrySubjectId.value, entryClassId.value)
    message.success(`已提交 ${res.submitted} 人成绩`)
    await reloadScores()
    await reloadProgress()
  } catch (e) {
    message.error((e as ApiError).detail || '提交失败')
  }
}

// ── 批量导入(KW-32) ──
const importFile = ref<File | null>(null)
const importResult = ref<ScoreImportResult | null>(null)
const importing = ref(false)
async function onDownloadTemplate() {
  if (!entrySubjectId.value) { message.warning('请先在成绩录入区选择科目'); return }
  try {
    await downloadScoreTemplate(examId, entrySubjectId.value)
  } catch (e) {
    message.error((e as ApiError).detail || '模板下载失败')
  }
}
function onPickFile(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0] ?? null
  importFile.value = f
  importResult.value = null
}
async function onImport() {
  if (!entrySubjectId.value) { message.warning('请先在成绩录入区选择科目'); return }
  if (!importFile.value) { message.warning('请先选择要导入的 Excel 文件'); return }
  importing.value = true
  try {
    importResult.value = await importScores(examId, entrySubjectId.value, importFile.value)
    if (importResult.value.errors.length) {
      // 有错一行都不写:后端全部通过才入库,错误逐行展示,正确行也不入库。
      message.warning(`导入失败 ${importResult.value.errors.length} 行,未入库任何一行`)
    } else {
      message.success(
        `导入完成:新增 ${importResult.value.created} 人,更新 ${importResult.value.updated} 人`,
      )
      await reloadScores()
      await reloadProgress()
    }
  } catch (e) {
    message.error((e as ApiError).detail || '导入失败')
  } finally {
    importing.value = false
  }
}

// ── 录入进度看板(KW-34) ──
const progress = ref<ScoreProgress | null>(null)
async function reloadProgress() {
  try {
    progress.value = await getScoreProgress(examId)
  } catch (e) {
    message.error((e as ApiError).detail || '录入进度加载失败')
  }
}

// ── 补考成绩登记(KW-35) ──
const makeups = ref<Makeup[]>([])
const makeupForm = ref({ name: '', exam_date: '', note: '' })
const selectedMakeupId = ref<number | null>(null)
const makeupSubjectId = ref<number | null>(null)
const makeupRows = ref<{ student_id: number; student_no: string; student_name: string; class_name: string; grade: number | null; score: number | null; status: string }[]>([])
const makeupLoading = ref(false)
const makeupStatusOptions = MAKEUP_SCORE_STATUSES.map((s) => ({ label: s, value: s }))
async function reloadMakeups() {
  try {
    makeups.value = (await listMakeups(examId)).items
  } catch (e) {
    message.error((e as ApiError).detail || '补考场次加载失败')
  }
}
async function addMakeup() {
  if (!makeupForm.value.name.trim()) { message.warning('请输入补考场次名称'); return }
  if (!makeupForm.value.exam_date) { message.warning('请选择补考日期'); return }
  try {
    await createMakeup(examId, {
      name: makeupForm.value.name.trim(),
      exam_date: makeupForm.value.exam_date,
      note: makeupForm.value.note.trim() || null,
    })
    message.success('补考场次已新建')
    makeupForm.value = { name: '', exam_date: '', note: '' }
    await reloadMakeups()
  } catch (e) {
    message.error((e as ApiError).detail || '补考场次新建失败')
  }
}
async function removeMakeup(m: Makeup) {
  try {
    await deleteMakeup(examId, m.id)
    message.success('已删除')
    if (selectedMakeupId.value === m.id) { selectedMakeupId.value = null; makeupRows.value = [] }
    await reloadMakeups()
  } catch (e) {
    message.error((e as ApiError).detail || '删除失败')
  }
}
async function reloadMakeupScores() {
  if (!selectedMakeupId.value || !makeupSubjectId.value) { makeupRows.value = []; return }
  makeupLoading.value = true
  try {
    const res = await listMakeupScores(examId, selectedMakeupId.value, makeupSubjectId.value)
    makeupRows.value = res.items.map((r: MakeupScore) => ({
      student_id: r.student_id, student_no: r.student_no, student_name: r.student_name,
      class_name: r.class_name, grade: r.grade, score: r.score, status: r.status || '正常',
    }))
  } catch (e) {
    message.error((e as ApiError).detail || '补考成绩加载失败')
  } finally {
    makeupLoading.value = false
  }
}
function makeupRowError(row: { score: number | null; status: string }): string | null {
  if (row.status !== '正常') return null
  return validateScore(row.score, fullScoreFor(makeupSubjectId.value))
}
const hasMakeupError = computed(() => makeupRows.value.some((r) => makeupRowError(r) !== null))
async function saveMakeupEntryScores() {
  if (!selectedMakeupId.value || !makeupSubjectId.value) {
    message.warning('请先选择补考场次与科目'); return
  }
  if (hasMakeupError.value) { message.error('存在超满分的补考成绩,请先修正再保存'); return }
  const payload = makeupRows.value
    .filter((r) => r.score !== null || r.status !== '正常')
    .map((r) => ({
      student_id: r.student_id,
      score: r.status === '正常' ? r.score : null,
      status: r.status,
    }))
  if (!payload.length) { message.warning('没有可保存的补考成绩'); return }
  try {
    const res = await saveMakeupScores(
      examId, selectedMakeupId.value, makeupSubjectId.value, payload,
    )
    message.success(`已保存 ${res.updated} 人补考成绩`)
    await reloadMakeupScores()
  } catch (e) {
    message.error((e as ApiError).detail || '补考成绩保存失败')
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
    const [teacherList, classList] = await Promise.all([
      listTeachers(exam.semester_id),
      listClassUnits(exam.semester_id),
    ])
    teachers.value = teacherList
    classes.value = classList
    if (examSubjects.value.length) {
      markingSubjectId.value = examSubjects.value[0].subject_id
      entrySubjectId.value = examSubjects.value[0].subject_id
      makeupSubjectId.value = examSubjects.value[0].subject_id
    }
    await Promise.all([reloadSettings(), reloadMarking(), reloadScoreItems(), reloadScores(), reloadProgress(), reloadMakeups()])
  } catch (e) {
    if ((e as ApiError).status === 403) forbidden.value = true
    else message.error((e as ApiError).detail || '加载失败')
  } finally {
    loading.value = false
  }
}
onMounted(() => { void reloadAll() })

function goBack() {
  void router.push({ name: 'exam-exam-detail', params: { id: examId } })
}
async function onMarkingSubjectChange() {
  await Promise.all([reloadMarking(), reloadScoreItems()])
}
async function onEntrySubjectChange() {
  await reloadScores()
}
</script>

<template>
  <div class="ios-page">
    <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap">
      <n-button text type="primary" @click="goBack">← 考试详情</n-button>
      <h1 class="ios-title">{{ examName ? `${examName} · 阅卷与成绩录入` : '阅卷与成绩录入' }}</h1>
    </div>
    <n-alert v-if="forbidden" type="error" style="margin-top: 16px">
      无权查看该考试(不在你的可见范围内)。
    </n-alert>
    <n-empty v-else-if="!loading && !examName" description="找不到该考试" style="margin-top: 24px" />

    <template v-else-if="examName">
      <!-- 成绩设置(KW-30) -->
      <div class="ios-section">
        <div class="ios-section-title">成绩设置</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            录入模式、补考口径、作弊计分、缺考统计口径、录分截止时间由教务定,保存后全校按此口径执行。
          </n-text>
          <n-space :wrap="true" align="center">
            <n-text>录入模式</n-text>
            <n-select
              v-model:value="settingsForm.entry_mode" :options="entryModeOptions"
              :disabled="!canManage" style="width: 150px"
            />
            <n-text>补考口径</n-text>
            <n-select
              v-model:value="settingsForm.makeup_mode" :options="makeupModeOptions"
              :disabled="!canManage" style="width: 180px"
            />
            <n-text>作弊计分</n-text>
            <n-select
              v-model:value="settingsForm.cheating_score_mode" :options="cheatingModeOptions"
              :disabled="!canManage" style="width: 150px"
            />
            <n-text>缺考计入平均分/及格率</n-text>
            <n-switch v-model:value="settingsForm.absent_counts" :disabled="!canManage" />
            <n-text>录分截止时间</n-text>
            <input
              v-model="settingsForm.score_deadline" type="datetime-local"
              :disabled="!canManage" style="width: 190px"
            />
            <n-button
              v-if="canManage" type="primary" data-testid="scores-save-settings"
              @click="saveSettings"
            >保存设置</n-button>
          </n-space>
        </div></div>
      </div>

      <!-- 阅卷分工(KW-30)与大题小分(KW-31) -->
      <div class="ios-section">
        <div class="ios-section-title">阅卷分工</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-space :wrap="true" align="center">
            <n-select
              v-model:value="markingSubjectId" :options="subjectOptions" clearable
              placeholder="选择科目" style="width: 150px" @update:value="onMarkingSubjectChange"
            />
            <template v-if="canManage">
              <n-select
                v-model:value="markingForm.teacher_id" :options="teacherOptions" filterable
                clearable placeholder="选择教师" style="width: 150px"
              />
              <n-select
                v-model:value="markingForm.role" :options="roleOptions" style="width: 110px"
              />
              <n-select
                v-model:value="markingForm.scope_type" :options="scopeTypeOptions"
                style="width: 90px"
              />
              <n-input
                v-model:value="markingForm.scope_value"
                placeholder="分工范围:如 1-3 班 / 第一大题" style="width: 200px"
              />
              <n-button type="primary" @click="addMarking">登记分工</n-button>
            </template>
          </n-space>
          <n-empty v-if="markingItems.length === 0" description="该科目暂无阅卷分工" style="margin-top: 12px" />
          <n-data-table
            v-else :columns="markingColumns" :data="markingItems" :bordered="false"
            :single-line="false" style="margin-top: 12px"
          />
          <template v-if="settingsForm.entry_mode === 'itemized'">
            <n-text depth="3" style="font-size: 12px; display: block; margin: 16px 0 8px">
              当前为“录大题小分”模式,请先为该科目登记大题与满分;录入时总分等于小分之和。
            </n-text>
            <n-space :wrap="true" align="center">
              <n-input v-model:value="itemForm.name" placeholder="大题名称,如 第一大题" style="width: 180px" />
              <n-input-number
                v-model:value="itemForm.max_score" :min="0" placeholder="大题满分"
                style="width: 110px" :disabled="!canManage"
              />
              <n-button v-if="canManage" @click="addScoreItem">添加大题</n-button>
            </n-space>
            <n-empty v-if="scoreItems.length === 0" description="尚未登记大题" style="margin-top: 12px" />
            <div v-for="it in scoreItems" :key="it.id" class="ios-row">
              <div class="ios-row-main">
                <div class="ios-row-title">{{ it.name }}</div>
                <div class="ios-row-sub">满分 {{ it.max_score }}</div>
              </div>
              <n-popconfirm v-if="canManage" @positive-click="removeScoreItem(it)">
                <template #trigger><n-button size="small" text type="error">删除</n-button></template>
                确定删除大题「{{ it.name }}」?
              </n-popconfirm>
            </div>
          </template>
        </div></div>
      </div>

      <!-- 成绩录入(KW-31、KW-33) -->
      <div class="ios-section">
        <div class="ios-section-title">成绩录入</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-space :wrap="true" align="center">
            <n-select
              v-model:value="entrySubjectId" :options="subjectOptions" clearable
              placeholder="选择科目" style="width: 150px" @update:value="onEntrySubjectChange"
            />
            <n-select
              v-model:value="entryClassId" :options="classOptions" clearable
              placeholder="班级" style="width: 170px" @update:value="reloadScores"
            />
            <n-select
              v-model:value="entryStatus" :options="statusOptions" clearable
              placeholder="成绩状态" style="width: 110px" @update:value="reloadScores"
            />
            <n-input
              v-model:value="entryQ" placeholder="按姓名或学号检索" clearable
              style="width: 180px" @change="reloadScores"
            />
            <n-button type="primary" @click="reloadScores">检索</n-button>
            <n-text depth="3" style="font-size: 12px">
              满分 {{ fullScoreFor(entrySubjectId) }} 分;回车跳到下一人;超满分即时报错并禁保存。
            </n-text>
          </n-space>
          <n-empty v-if="!scoresLoading && rows.length === 0" description="暂无可录入的学生,请先选择科目" style="margin-top: 12px" />
          <table v-else class="ios-table" style="margin-top: 12px">
            <thead>
              <tr>
                <th>学号</th><th>姓名</th><th>年级</th><th>班级</th>
                <th v-if="settingsForm.entry_mode === 'itemized' && entryItemsFor(entrySubjectId).length">
                  <span v-for="it in entryItemsFor(entrySubjectId)" :key="it.id" style="margin-right: 8px">
                    {{ it.name }}({{ it.max_score }})
                  </span>
                </th>
                <th>总分</th><th>状态</th><th>已提交</th><th>提示</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, i) in rows" :key="row.student_id">
                <td>{{ row.student_no }}</td>
                <td>{{ row.student_name }}</td>
                <td>{{ row.grade != null ? `${row.grade}年级` : '—' }}</td>
                <td>{{ row.class_name }}</td>
                <td v-if="settingsForm.entry_mode === 'itemized' && entryItemsFor(entrySubjectId).length">
                  <span v-for="it in entryItemsFor(entrySubjectId)" :key="it.id" style="margin-right: 6px">
                    <input
                      :ref="setScoreInputEl(i)" type="number" min="0" :max="it.max_score"
                      :value="row.items[it.id] ?? ''" :disabled="row.status !== '正常'"
                      style="width: 64px" :data-testid="`score-item-input-${row.student_id}-${it.id}`"
                      @input="row.items[it.id] = ($event.target as HTMLInputElement).value === '' ? null : Number(($event.target as HTMLInputElement).value)"
                      @keydown.enter="focusNextRow(i)"
                    >
                  </span>
                </td>
                <td>
                  <template v-if="row.status === '正常'">
                    <input
                      v-if="settingsForm.entry_mode !== 'itemized' || !entryItemsFor(entrySubjectId).length"
                      :ref="setScoreInputEl(i)" type="number" min="0"
                      :max="fullScoreFor(entrySubjectId)"
                      :value="row.score ?? ''" style="width: 80px"
                      :data-testid="`score-input-${row.student_id}`"
                      @input="row.score = ($event.target as HTMLInputElement).value === '' ? null : Number(($event.target as HTMLInputElement).value)"
                      @keydown.enter="focusNextRow(i)"
                    >
                    <span v-else data-testid="score-itemized-total">{{ itemizedTotal(entryItemsFor(entrySubjectId).map((it) => row.items[it.id])) }}</span>
                  </template>
                  <span v-else>{{ effectiveScoreText(row) }}</span>
                </td>
                <td>
                  <n-select
                    v-model:value="row.status" :options="statusOptions" style="width: 96px"
                    :data-testid="`score-status-${row.student_id}`"
                  />
                </td>
                <td>{{ row.submitted ? '已提交' : '—' }}</td>
                <td>
                  <n-text
                    v-if="rowError(row)" type="error" style="font-size: 12px"
                    :data-testid="`score-error-${row.student_id}`"
                  >{{ rowError(row) }}</n-text>
                  <span v-else>—</span>
                </td>
              </tr>
            </tbody>
          </table>
          <n-space :wrap="true" align="center" style="margin-top: 12px">
            <n-text depth="3" style="font-size: 13px">
              共 {{ rows.length }} 人,已录 {{ enteredCount }} 人
            </n-text>
            <n-button
              type="primary" :disabled="hasRowError || !entrySubjectId"
              data-testid="scores-save" @click="saveEntryScores"
            >保存成绩</n-button>
            <n-popconfirm @positive-click="submitEntryScores">
              <template #trigger>
                <n-button :disabled="hasRowError || !entrySubjectId" data-testid="scores-submit">提交成绩</n-button>
              </template>
              提交后进入校对锁定流程(下批),请确认本班本科目成绩已录完。
            </n-popconfirm>
            <n-text v-if="hasRowError" type="error" style="font-size: 12px">
              存在超满分或小分超限的成绩,请先修正再保存或提交。
            </n-text>
          </n-space>
        </div></div>
      </div>

      <!-- 批量导入(KW-32) -->
      <div class="ios-section">
        <div class="ios-section-title">批量导入</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            先下载本科目模板再填,不要自改列名;导入时校验学号、分数范围与重复行,错误逐行提示,有错一行都不写。
            导入只录总分,会清空已录的大题小分。
          </n-text>
          <n-space :wrap="true" align="center">
            <n-button @click="onDownloadTemplate">下载成绩模板</n-button>
            <input type="file" accept=".xlsx,.xls" data-testid="scores-import-file" @change="onPickFile">
            <n-button
              type="primary" :loading="importing" :disabled="!importFile"
              data-testid="scores-import" @click="onImport"
            >上传导入</n-button>
          </n-space>
          <n-alert
            v-if="importResult && importResult.errors.length" type="warning"
            title="以下行导入失败,未入库任何一行" style="margin-top: 12px"
            data-testid="scores-import-errors"
          >
            <div
              v-for="(err, i) in formatImportErrors(importResult.errors)" :key="i"
              style="font-size: 13px"
            >{{ err }}</div>
          </n-alert>
          <n-alert
            v-else-if="importResult" type="success" style="margin-top: 12px"
            data-testid="scores-import-ok"
          >
            导入完成:新增 {{ importResult.created }} 人,更新 {{ importResult.updated }} 人。
          </n-alert>
        </div></div>
      </div>

      <!-- 录入进度看板(KW-34) -->
      <div class="ios-section">
        <div class="ios-section-title">录入进度看板</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-button size="small" style="margin-bottom: 12px" @click="reloadProgress">刷新进度</n-button>
          <n-empty v-if="!progress || progress.subjects.length === 0" description="暂无录入进度" />
          <template v-for="s in progress?.subjects ?? []" :key="s.subject_id">
            <div class="ios-row-title" style="margin: 8px 0">{{ s.subject_name }}</div>
            <table class="ios-table">
              <thead><tr><th>年级</th><th>班级</th><th>应录</th><th>已录</th><th>已提交</th><th>状态</th></tr></thead>
              <tbody>
                <tr v-for="c in s.classes" :key="c.class_unit_id">
                  <td>{{ c.grade != null ? `${c.grade}年级` : '—' }}</td>
                  <td>{{ c.class_name }}</td>
                  <td>{{ c.total }}</td>
                  <td>{{ c.entered }}</td>
                  <td>{{ c.submitted }}</td>
                  <td>
                    <span
                      :class="c.status === '已提交' ? 'ios-chip' : c.status === '录入中' ? 'ios-chip-gray' : 'ios-chip-gray'"
                    >{{ c.status }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </template>
        </div></div>
      </div>

      <!-- 补考成绩登记(KW-35) -->
      <div class="ios-section">
        <div class="ios-section-title">补考成绩登记</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            补考单独建场次、与正考成绩并列保存;是否覆盖或取高按成绩设置里的补考口径执行,口径未定前只做单独标注。
          </n-text>
          <n-space :wrap="true" align="center">
            <template v-if="canManage">
              <n-input v-model:value="makeupForm.name" placeholder="补考场次名称,如 数学补考" style="width: 180px" />
              <input v-model="makeupForm.exam_date" type="date" style="width: 150px">
              <n-input v-model:value="makeupForm.note" placeholder="备注(选填)" style="width: 160px" />
              <n-button type="primary" @click="addMakeup">新建补考场次</n-button>
            </template>
          </n-space>
          <n-empty v-if="makeups.length === 0" description="暂无补考场次" style="margin-top: 12px" />
          <div v-for="m in makeups" :key="m.id" class="ios-row">
            <div class="ios-row-main">
              <div class="ios-row-title">{{ m.name }}</div>
              <div class="ios-row-sub">{{ m.exam_date }}{{ m.note ? ` · ${m.note}` : '' }}</div>
            </div>
            <n-button
              size="small" :type="selectedMakeupId === m.id ? 'primary' : 'default'"
              @click="selectedMakeupId = m.id; reloadMakeupScores()"
            >{{ selectedMakeupId === m.id ? '已选中' : '录入补考成绩' }}</n-button>
            <n-popconfirm v-if="canManage" @positive-click="removeMakeup(m)">
              <template #trigger><n-button size="small" text type="error">删除</n-button></template>
              确定删除补考场次「{{ m.name }}」?
            </n-popconfirm>
          </div>
          <template v-if="selectedMakeupId">
            <n-space :wrap="true" align="center" style="margin-top: 12px">
              <n-select
                v-model:value="makeupSubjectId" :options="subjectOptions" clearable
                placeholder="选择科目" style="width: 150px" @update:value="reloadMakeupScores"
              />
              <n-text depth="3" style="font-size: 12px">
                补考成绩状态只有正常/缺考/免考,没有作弊;满分 {{ fullScoreFor(makeupSubjectId) }} 分。
              </n-text>
            </n-space>
            <n-empty v-if="!makeupLoading && makeupRows.length === 0" description="暂无补考学生,请先选择科目" style="margin-top: 12px" />
            <table v-else class="ios-table" style="margin-top: 12px">
              <thead><tr><th>学号</th><th>姓名</th><th>年级</th><th>班级</th><th>补考成绩</th><th>状态</th><th>提示</th></tr></thead>
              <tbody>
                <tr v-for="row in makeupRows" :key="row.student_id">
                  <td>{{ row.student_no }}</td>
                  <td>{{ row.student_name }}</td>
                  <td>{{ row.grade != null ? `${row.grade}年级` : '—' }}</td>
                  <td>{{ row.class_name }}</td>
                  <td>
                    <input
                      v-if="row.status === '正常'" type="number" min="0"
                      :max="fullScoreFor(makeupSubjectId)" :value="row.score ?? ''"
                      style="width: 80px" :data-testid="`makeup-score-input-${row.student_id}`"
                      @input="row.score = ($event.target as HTMLInputElement).value === '' ? null : Number(($event.target as HTMLInputElement).value)"
                    >
                    <span v-else>—</span>
                  </td>
                  <td>
                    <n-select
                      v-model:value="row.status" :options="makeupStatusOptions"
                      style="width: 96px"
                    />
                  </td>
                  <td>
                    <n-text
                      v-if="makeupRowError(row)" type="error" style="font-size: 12px"
                      :data-testid="`makeup-score-error-${row.student_id}`"
                    >{{ makeupRowError(row) }}</n-text>
                    <span v-else>—</span>
                  </td>
                </tr>
              </tbody>
            </table>
            <n-space :wrap="true" style="margin-top: 12px">
              <n-button
                type="primary" :disabled="hasMakeupError || !makeupSubjectId"
                data-testid="makeup-scores-save" @click="saveMakeupEntryScores"
              >保存补考成绩</n-button>
              <n-text v-if="hasMakeupError" type="error" style="font-size: 12px">
                存在超满分的补考成绩,请先修正再保存。
              </n-text>
            </n-space>
          </template>
        </div></div>
      </div>
    </template>
  </div>
</template>
