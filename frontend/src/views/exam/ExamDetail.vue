<script setup lang="ts">
import {
  NAlert, NButton, NDataTable, NEmpty, NInput, NInputNumber, NModal, NPopconfirm, NSelect,
  NSpace, NText, useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { computed, h, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import {
  ARRANGEMENT_TYPES, EXAM_STATUSES, EXAM_TYPES, PARTICIPANT_STATUSES,
  addParticipants, canAdvanceExamStatus, changeExamStatus, checkExamSchedule,
  createSpecialArrangement, deleteParticipant, deleteSpecialArrangement, getExam,
  getPaperInfo, isExamDraft, isExamStatusBackward, listParticipants, listSpecialArrangements,
  generateParticipants, nextExamStatus, saveExamSubjects, savePaperInfo, updateExam,
  updateParticipant, updateSpecialArrangement, listStudents,
} from '@/api/exam'
import type {
  ExamDetail, ExamParticipant, PaperInfoItem, ScheduleConflict, SpecialArrangement,
  Student,
} from '@/api/exam'
import { listClassUnits, listSubjects, listTeachers } from '@/api/basedata'
import type { ClassUnit, Subject, Teacher } from '@/api/basedata'
import { useAuthStore } from '@/stores/auth'

const message = useMessage()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const examId = Number(route.params.id)
// 考试管理是教务职责:写操作只限 admin/director,越权时后端回 403,前端原样展示。
const canManage = computed(() => auth.hasRole('admin') || auth.hasRole('director'))

const exam = ref<ExamDetail | null>(null)
const loading = ref(false)
const forbidden = ref(false)
const isDraft = computed(() => exam.value ? isExamDraft(exam.value.status) : false)
const nextStatus = computed(() => exam.value ? nextExamStatus(exam.value.status) : null)
const canAdvance = computed(() => exam.value ? canAdvanceExamStatus(exam.value.status) : false)
const backwardOptions = computed(() => {
  if (!exam.value) return []
  const i = EXAM_STATUSES.indexOf(exam.value.status as (typeof EXAM_STATUSES)[number])
  return EXAM_STATUSES.slice(0, Math.max(i, 0)).map((s) => ({ label: s, value: s }))
})

const allSubjects = ref<Subject[]>([])
const teachers = ref<Teacher[]>([])
const classes = ref<ClassUnit[]>([])
const students = ref<Student[]>([])
const classOptions = computed(() =>
  classes.value.map((c) => ({ label: `${c.grade} 年级 ${c.name}`, value: c.id })),
)
const teacherOptions = computed(() =>
  teachers.value.map((t) => ({ label: t.name, value: t.id })),
)
const subjectOptions = computed(() =>
  allSubjects.value.map((s) => ({ label: s.name, value: s.id })),
)
const gradeOptions = computed(() => {
  const grades = [...new Set(classes.value.map((c) => c.grade))].sort((a, b) => a - b)
  return (grades.length ? grades : [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])
    .map((g) => ({ label: `${g} 年级`, value: g }))
})
const studentOptions = computed(() =>
  students.value.map((s) => ({ label: `${s.name}(${s.student_no}) ${s.class_name}`, value: s.id })),
)

async function reload() {
  loading.value = true
  forbidden.value = false
  try {
    exam.value = await getExam(examId)
    const sid = exam.value.semester_id
    const [subjects, teacherList, classList, studentList] = await Promise.all([
      listSubjects(sid),
      listTeachers(sid),
      listClassUnits(sid),
      listStudents({ semesterId: sid, limit: 100 }),
    ])
    allSubjects.value = subjects
    teachers.value = teacherList
    classes.value = classList
    students.value = studentList.items
    scheduleRows.value = (exam.value.subjects ?? []).map((s) => ({ ...s }))
    await Promise.all([reloadParticipants(), reloadPaperInfo(), reloadArrangements()])
  } catch (e) {
    if ((e as ApiError).status === 403) forbidden.value = true
    else message.error((e as ApiError).detail || '加载失败')
  } finally {
    loading.value = false
  }
}
onMounted(() => { void reload() })

function goBack() {
  void router.push({ name: 'exam-exams' })
}

function goArrange() {
  void router.push({ name: 'exam-exam-arrange', params: { id: examId } })
}

function goInvigilation() {
  void router.push({ name: 'exam-exam-invigilation', params: { id: examId } })
}

function goScores() {
  void router.push({ name: 'exam-exam-scores', params: { id: examId } })
}

function goPublish() {
  void router.push({ name: 'exam-exam-publish', params: { id: examId } })
}

function goAnalysis() {
  void router.push({ name: 'exam-exam-analysis', params: { id: examId } })
}

function goTeacherScores() {
  void router.push({ name: 'exam-exam-teacher-scores', params: { id: examId } })
}

function goNotifications() {
  void router.push({ name: 'exam-exam-notifications', params: { id: examId } })
}

function goArchive() {
  void router.push({ name: 'exam-exam-archive', params: { id: examId } })
}

// ── 基本信息编辑(仅草稿可改,Kw-08) ──
const showEdit = ref(false)
const editForm = ref({ name: '', exam_type: '月考', grades: [] as number[], description: '' })
const typeOptions = EXAM_TYPES.map((t) => ({ label: t, value: t }))
function openEdit() {
  if (!exam.value) return
  editForm.value = {
    name: exam.value.name, exam_type: exam.value.exam_type,
    grades: [...(exam.value.grades ?? [])], description: exam.value.description ?? '',
  }
  showEdit.value = true
}
async function saveEdit() {
  if (!exam.value) return
  if (!editForm.value.name.trim()) { message.warning('请输入考试名称'); return }
  if (!editForm.value.grades.length) { message.warning('请至少选择一个参试年级'); return }
  try {
    await updateExam(exam.value.id, {
      name: editForm.value.name.trim(),
      exam_type: editForm.value.exam_type,
      grades: editForm.value.grades,
      description: editForm.value.description.trim() || null,
    })
    showEdit.value = false
    message.success('已储存')
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '储存失败')
  }
}

// ── 状态流转(KW-11):按顺序展示,当前高亮;前进直接推进,回退二次确认并写备注 ──
async function advanceStatus() {
  if (!exam.value || !nextStatus.value) return
  try {
    await changeExamStatus(exam.value.id, nextStatus.value)
    message.success(`已推进到${nextStatus.value}`)
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '状态流转失败')
  }
}
const showBackward = ref(false)
const backwardForm = ref({ to_status: '' as string, note: '' })
function openBackward() {
  backwardForm.value = { to_status: backwardOptions.value[0]?.value ?? '', note: '' }
  showBackward.value = true
}
async function saveBackward() {
  if (!exam.value) return
  if (!backwardForm.value.to_status) { message.warning('请选择要回退到的状态'); return }
  if (!isExamStatusBackward(exam.value.status, backwardForm.value.to_status)) {
    message.warning('只能回退到当前状态之前的状态')
    return
  }
  if (!backwardForm.value.note.trim()) { message.warning('回退须写备注留痕'); return }
  try {
    await changeExamStatus(exam.value.id, backwardForm.value.to_status, backwardForm.value.note.trim())
    showBackward.value = false
    message.success(`已回退到${backwardForm.value.to_status}`)
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '回退失败')
  }
}

// ── 考试日程(KW-09):按科目设日期与起止时间;保存后跑冲突检查,只提示不阻断 ──
interface ScheduleRow {
  subject_id: number
  subject_name: string
  exam_date: string | null
  start_time: string | null
  end_time: string | null
  full_score: number | null
}
const scheduleRows = ref<ScheduleRow[]>([])
const conflicts = ref<ScheduleConflict[]>([])
const conflictChecked = ref(false)
const addSubjectIds = ref<number[]>([])
const addableSubjects = computed(() =>
  subjectOptions.value.filter((o) => !scheduleRows.value.some((r) => r.subject_id === o.value)),
)
/** 全选:把当前可加的科目一次全部勾上,再点“添加科目”一次加完。 */
function selectAllAddableSubjects() {
  addSubjectIds.value = addableSubjects.value.map((o) => o.value)
}
function addScheduleRow() {
  if (!addSubjectIds.value.length) { message.warning('请选择科目'); return }
  for (const id of addSubjectIds.value) {
    const s = allSubjects.value.find((x) => x.id === id)
    if (!s) continue
    if (scheduleRows.value.some((r) => r.subject_id === s.id)) continue
    scheduleRows.value.push({
      subject_id: s.id, subject_name: s.name,
      exam_date: null, start_time: null, end_time: null, full_score: null,
    })
  }
  addSubjectIds.value = []
}
function removeScheduleRow(row: ScheduleRow) {
  scheduleRows.value = scheduleRows.value.filter((r) => r.subject_id !== row.subject_id)
}
async function saveSchedule() {
  if (!exam.value) return
  // 后端 ExamSubjectIn 要求每科日期与起止时间必填(null 会 422):先在前端拦住,
  // 满分可空。缺项时不发请求,逐科提示补填。
  const missing = scheduleRows.value.find((r) => !r.exam_date || !r.start_time || !r.end_time)
  if (missing) {
    message.warning(`请先补填「${missing.subject_name}」的考试日期与起止时间`)
    return
  }
  try {
    await saveExamSubjects(exam.value.id, scheduleRows.value.map((r) => ({
      subject_id: r.subject_id,
      exam_date: r.exam_date,
      start_time: r.start_time,
      end_time: r.end_time,
      full_score: r.full_score,
    })))
    const res = await checkExamSchedule(exam.value.id)
    conflicts.value = res.conflicts
    conflictChecked.value = true
    if (res.conflicts.length) message.warning(`发现 ${res.conflicts.length} 项日程冲突,仅提示,不阻断发布`)
    else message.success('日程已保存,无冲突')
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '保存失败')
  }
}

// ── 参试名单(KW-10) ──
const filterClass = ref<number[]>([])
const filterPStatus = ref<string | null>(null)
const filterPQ = ref('')
const pStatusOptions = PARTICIPANT_STATUSES.map((s) => ({ label: s, value: s }))
const participants = ref<ExamParticipant[]>([])
const pTotal = ref(0)
const pLoading = ref(false)
async function reloadParticipants() {
  if (!exam.value) return
  pLoading.value = true
  try {
    const res = await listParticipants(exam.value.id, {
      classUnitIds: filterClass.value.length ? filterClass.value : undefined,
      status: filterPStatus.value,
      q: filterPQ.value || undefined,
    })
    participants.value = res.items
    pTotal.value = res.total
  } catch (e) {
    message.error((e as ApiError).detail || '参试名单加载失败')
  } finally {
    pLoading.value = false
  }
}
async function onGenerate() {
  if (!exam.value) return
  try {
    const res = await generateParticipants(exam.value.id)
    message.success(`已生成参试名单:新增 ${res.created} 人,跳过 ${res.skipped} 人`)
    await reloadParticipants()
  } catch (e) {
    message.error((e as ApiError).detail || '生成失败')
  }
}
const showAddP = ref(false)
const addPForm = ref({ student_ids: [] as number[], note: '' })
function openAddP() {
  addPForm.value = { student_ids: [], note: '' }
  showAddP.value = true
}
async function saveAddP() {
  if (!exam.value || !addPForm.value.student_ids.length) { message.warning('请选择学生'); return }
  try {
    const res = await addParticipants(exam.value.id, {
      student_ids: addPForm.value.student_ids,
      note: addPForm.value.note.trim() || null,
    })
    showAddP.value = false
    message.success(res.skipped ? `已增补 ${res.created} 人,跳过 ${res.skipped} 人(已在名单中)` : `已增补 ${res.created} 人`)
    await reloadParticipants()
  } catch (e) {
    message.error((e as ApiError).detail || '增补失败')
  }
}
async function markParticipant(p: ExamParticipant, status: string) {
  if (!exam.value) return
  try {
    await updateParticipant(exam.value.id, p.id, { status })
    message.success(`已标记为${status}`)
    await reloadParticipants()
  } catch (e) {
    message.error((e as ApiError).detail || '标记失败')
  }
}
async function removeParticipant(p: ExamParticipant) {
  if (!exam.value) return
  try {
    await deleteParticipant(exam.value.id, p.id)
    message.success('已删除')
    await reloadParticipants()
  } catch (e) {
    message.error((e as ApiError).detail || '删除失败')
  }
}
const participantColumns: DataTableColumns<ExamParticipant> = [
  { title: '学号', key: 'student_no', width: 110 },
  { title: '姓名', key: 'student_name', width: 90 },
  { title: '班级', key: 'class_name', render: (row) => row.class_name ?? '—' },
  { title: '状态', key: 'status', width: 80 },
  { title: '备注', key: 'note', render: (row) => row.note ?? '—' },
  {
    title: '操作',
    key: 'actions',
    width: 260,
    render: (row) => h(NSpace, { size: 'small' }, {
      default: () => [
        ...(row.status !== '缺考' ? [h(NButton, { size: 'small', text: true, onClick: () => markParticipant(row, '缺考') }, () => '标记缺考')] : []),
        ...(row.status !== '免考' ? [h(NButton, { size: 'small', text: true, onClick: () => markParticipant(row, '免考') }, () => '标记免考')] : []),
        ...(row.status !== '正常' ? [h(NButton, { size: 'small', text: true, onClick: () => markParticipant(row, '正常') }, () => '恢复正常')] : []),
        h(NPopconfirm, { onPositiveClick: () => removeParticipant(row) }, {
          trigger: () => h(NButton, { size: 'small', text: true, type: 'error' }, () => '删除'),
          default: () => '确定从参试名单删除该学生?',
        }),
      ],
    }),
  },
]

// ── 命题与试卷信息(KW-13):只登记分工信息,不做题库组卷 ──
const paperRows = ref<PaperInfoItem[]>([])
async function reloadPaperInfo() {
  if (!exam.value) return
  try {
    const res = await getPaperInfo(exam.value.id)
    paperRows.value = res.items.length
      ? res.items
      : scheduleRows.value.map((r) => ({
        subject_id: r.subject_id, subject_name: r.subject_name,
        setter_teacher_id: null, reviewer_teacher_id: null, paper_count: null,
      }))
  } catch (e) {
    message.error((e as ApiError).detail || '命题信息加载失败')
  }
}
async function savePaper() {
  if (!exam.value) return
  try {
    await savePaperInfo(exam.value.id, paperRows.value)
    message.success('命题与试卷信息已保存')
  } catch (e) {
    message.error((e as ApiError).detail || '保存失败')
  }
}

// ── 特殊考生安排(KW-14) ──
const arrangements = ref<SpecialArrangement[]>([])
async function reloadArrangements() {
  if (!exam.value) return
  try {
    arrangements.value = (await listSpecialArrangements(exam.value.id)).items
  } catch (e) {
    message.error((e as ApiError).detail || '特殊安排加载失败')
  }
}
const showArr = ref(false)
const editingArrId = ref<number | null>(null)
const arrForm = ref({ student_id: null as number | null, arrangement_type: '单独考场', detail: '' })
const arrTypeOptions = ARRANGEMENT_TYPES.map((t) => ({ label: t, value: t }))
function openArrCreate() {
  editingArrId.value = null
  arrForm.value = { student_id: null, arrangement_type: '单独考场', detail: '' }
  showArr.value = true
}
function openArrEdit(a: SpecialArrangement) {
  editingArrId.value = a.id
  arrForm.value = {
    student_id: a.student_id, arrangement_type: a.arrangement_type, detail: a.detail ?? '',
  }
  showArr.value = true
}
async function saveArr() {
  if (!exam.value) return
  if (!arrForm.value.student_id) { message.warning('请选择学生'); return }
  try {
    if (editingArrId.value) {
      await updateSpecialArrangement(exam.value.id, editingArrId.value, {
        arrangement_type: arrForm.value.arrangement_type,
        detail: arrForm.value.detail.trim() || null,
      })
    } else {
      await createSpecialArrangement(exam.value.id, {
        student_id: arrForm.value.student_id,
        arrangement_type: arrForm.value.arrangement_type,
        detail: arrForm.value.detail.trim() || null,
      })
    }
    showArr.value = false
    message.success('已储存')
    await reloadArrangements()
  } catch (e) {
    message.error((e as ApiError).detail || '储存失败')
  }
}
async function removeArr(a: SpecialArrangement) {
  if (!exam.value) return
  try {
    await deleteSpecialArrangement(exam.value.id, a.id)
    message.success('已删除')
    await reloadArrangements()
  } catch (e) {
    message.error((e as ApiError).detail || '删除失败')
  }
}
function arrStudentName(a: SpecialArrangement): string {
  if (a.student_name) return `${a.student_name}${a.student_no ? `(${a.student_no})` : ''}`
  const s = students.value.find((x) => x.id === a.student_id)
  return s ? `${s.name}(${s.student_no})` : `学生 ${a.student_id}`
}
</script>

<template>
  <div class="ios-page">
    <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap">
      <n-button text type="primary" @click="goBack">← 考试列表</n-button>
      <h1 class="ios-title">{{ exam?.name ?? '考试详情' }}</h1>
    </div>

    <n-alert v-if="forbidden" type="error" style="margin-top: 16px">
      无权查看该考试(不在你的可见范围内)。
    </n-alert>
    <n-empty v-else-if="!loading && !exam" description="找不到该考试" style="margin-top: 24px" />

    <template v-else-if="exam">
      <!-- 基本信息与状态流转(KW-08、KW-11) -->
      <div class="ios-section">
        <div class="ios-section-title">基本信息与状态流转</div>
        <div class="ios-card"><div class="ios-card-body">
          <div class="ios-row">
            <div class="ios-row-main">
              <div class="ios-row-title">{{ exam.name }}</div>
              <div class="ios-row-sub">
                {{ exam.exam_type }} · {{ (exam.grades ?? []).map((g) => `${g} 年级`).join('、') }}
                · 参试 {{ exam.participant_count }} 人
                {{ exam.description ? ` · ${exam.description}` : '' }}
              </div>
            </div>
            <n-button v-if="canManage && isDraft" size="small" type="primary" @click="openEdit">编辑</n-button>
            <n-button size="small" @click="goArrange">考场编排</n-button>
            <n-button size="small" data-testid="exam-go-invigilation" @click="goInvigilation">监考安排</n-button>
            <n-button size="small" data-testid="exam-go-scores" @click="goScores">阅卷与成绩录入</n-button>
            <n-button size="small" data-testid="exam-go-publish" @click="goPublish">发布与校对锁定</n-button>
            <n-button size="small" data-testid="exam-go-analysis" @click="goAnalysis">成绩分析</n-button>
            <n-button size="small" data-testid="exam-go-report-scores" @click="goTeacherScores">成绩单与查询</n-button>
            <n-button size="small" data-testid="exam-go-notifications" @click="goNotifications">通知与提醒</n-button>
            <n-button size="small" data-testid="exam-go-archive" @click="goArchive">归档与备份</n-button>
          </div>
          <div class="ios-row">
            <div class="ios-row-main">
              <n-space :wrap="true" align="center">
                <span
                  v-for="s in EXAM_STATUSES" :key="s"
                  :class="s === exam.status ? 'ios-chip' : 'ios-chip-gray'"
                  :data-testid="s === exam.status ? 'exam-current-status' : undefined"
                  style="font-size: 13px; padding: 4px 12px"
                >{{ s }}</span>
              </n-space>
              <n-text depth="3" style="font-size: 12px; display: block; margin-top: 6px">
                状态按顺序流转:草稿→已发布→进行中→成绩处理中→已发布成绩→已归档;回退须写备注留痕。
                <span v-if="!isDraft">非草稿状态下基本信息与日程只读。</span>
              </n-text>
            </div>
          </div>
          <div v-if="canManage" class="ios-row">
            <n-space :wrap="true">
              <n-button
                v-if="canAdvance" type="primary" data-testid="exam-advance"
                @click="advanceStatus"
              >推进到{{ nextStatus }}</n-button>
              <n-text v-else depth="3" style="font-size: 13px">已归档,状态流转已结束。</n-text>
              <n-button
                v-if="backwardOptions.length" data-testid="exam-backward"
                @click="openBackward"
              >回退状态</n-button>
            </n-space>
          </div>
        </div></div>
      </div>

      <!-- 考试日程(KW-09) -->
      <div class="ios-section">
        <div class="ios-section-title">考试日程</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-alert
            v-if="conflictChecked && conflicts.length" type="warning" style="margin-bottom: 12px"
            data-testid="exam-schedule-conflicts"
          >
            <div style="font-weight: 600">发现 {{ conflicts.length }} 项日程冲突(仅提示,不阻断发布):</div>
            <div v-for="c in conflicts" :key="c.subject_id" style="font-size: 13px">
              {{ c.subject_name }}: {{ c.reason }}
            </div>
          </n-alert>
          <n-alert
            v-else-if="conflictChecked" type="success" style="margin-bottom: 12px"
          >日程无冲突。</n-alert>
          <table class="ios-table">
            <thead><tr><th>科目</th><th>考试日期</th><th>开始时间</th><th>结束时间</th><th>满分</th><th /></tr></thead>
            <tbody>
              <tr v-for="r in scheduleRows" :key="r.subject_id">
                <td>{{ r.subject_name }}</td>
                <td><input v-model="r.exam_date" type="date" :disabled="!isDraft || !canManage" style="width: 150px"></td>
                <td><input v-model="r.start_time" type="time" :disabled="!isDraft || !canManage" style="width: 110px"></td>
                <td><input v-model="r.end_time" type="time" :disabled="!isDraft || !canManage" style="width: 110px"></td>
                <td><n-input-number v-model:value="r.full_score" :min="0" :disabled="!isDraft || !canManage" placeholder="满分" style="width: 90px" /></td>
                <td><n-button v-if="isDraft && canManage" size="small" text type="error" @click="removeScheduleRow(r)">移除</n-button></td>
              </tr>
            </tbody>
          </table>
          <n-empty v-if="scheduleRows.length === 0" description="尚未编排日程,请先添加科目" />
          <n-space :wrap="true" align="center" style="margin-top: 12px">
            <template v-if="isDraft && canManage">
              <n-select
                v-model:value="addSubjectIds" :options="addableSubjects" multiple clearable
                max-tag-count="responsive" placeholder="选择科目(可多选)" style="width: 240px"
                data-testid="schedule-add-subjects"
              />
              <n-button size="small" data-testid="schedule-select-all" @click="selectAllAddableSubjects">全选</n-button>
              <n-button @click="addScheduleRow">添加科目</n-button>
              <n-button type="primary" @click="saveSchedule">保存日程并检查冲突</n-button>
            </template>
            <n-text depth="3" style="font-size: 12px">冲突检查只提示,不阻断发布;是否强制发布由教务决定。</n-text>
          </n-space>
        </div></div>
      </div>

      <!-- 参试名单(KW-10) -->
      <div class="ios-section">
        <div class="ios-section-title">参试名单</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-space :wrap="true" align="center">
            <n-select
              v-model:value="filterClass" :options="classOptions" multiple clearable
              max-tag-count="responsive" placeholder="班级(可多选)" style="width: 220px"
              data-testid="participant-filter-class" @update:value="reloadParticipants"
            />
            <n-select
              v-model:value="filterPStatus" :options="pStatusOptions" clearable
              placeholder="参试状态" style="width: 120px" @update:value="reloadParticipants"
            />
            <n-input
              v-model:value="filterPQ" placeholder="按姓名或学号检索" clearable
              style="width: 200px" @change="reloadParticipants"
            />
            <n-button type="primary" @click="reloadParticipants">检索</n-button>
            <template v-if="canManage">
              <n-button @click="onGenerate">一键生成参试名单</n-button>
              <n-button @click="openAddP">个别增补</n-button>
            </template>
          </n-space>
          <n-text depth="3" style="font-size: 12px; display: block; margin-top: 8px">
            名单一键按年级/班级从学生档案生成;可个别增补借读、休学等学生,预标记缺考/免考。
          </n-text>
          <n-empty v-if="!pLoading && participants.length === 0" description="暂无参试学生" style="margin-top: 12px" />
          <n-data-table
            v-else :columns="participantColumns" :data="participants" :loading="pLoading"
            :bordered="false" :single-line="false" style="margin-top: 12px"
          />
          <n-text depth="3" style="font-size: 13px">共 {{ pTotal }} 人</n-text>
        </div></div>
      </div>

      <!-- 命题与试卷信息(KW-13) -->
      <div class="ios-section">
        <div class="ios-section-title">命题与试卷信息</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            只登记命题分工信息,不做题库组卷;命题在线下完成。
          </n-text>
          <table class="ios-table">
            <thead><tr><th>科目</th><th>命题教师</th><th>审题教师</th><th>试卷份数</th></tr></thead>
            <tbody>
              <tr v-for="r in paperRows" :key="r.subject_id">
                <td>{{ r.subject_name ?? allSubjects.find((s) => s.id === r.subject_id)?.name ?? r.subject_id }}</td>
                <td><n-select v-model:value="r.setter_teacher_id" :options="teacherOptions" clearable placeholder="选择命题教师" :disabled="!canManage" style="width: 150px" /></td>
                <td><n-select v-model:value="r.reviewer_teacher_id" :options="teacherOptions" clearable placeholder="选择审题教师" :disabled="!canManage" style="width: 150px" /></td>
                <td><n-input-number v-model:value="r.paper_count" :min="0" :disabled="!canManage" placeholder="份数" style="width: 100px" /></td>
              </tr>
            </tbody>
          </table>
          <n-empty v-if="paperRows.length === 0" description="请先在考试日程里添加科目" />
          <n-button v-if="canManage && paperRows.length" type="primary" style="margin-top: 12px" @click="savePaper">保存命题信息</n-button>
        </div></div>
      </div>

      <!-- 特殊考生安排(KW-14) -->
      <div class="ios-section">
        <div class="ios-section-title">特殊考生安排</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-alert type="info" style="margin-bottom: 12px" data-testid="special-arrangement-privacy">
            特殊考生安排涉及学生隐私,仅教务与相关监考教师可见,请勿转发到群消息或公开场合。
          </n-alert>
          <n-button v-if="canManage" style="margin-bottom: 12px" @click="openArrCreate">登记特殊安排</n-button>
          <n-empty v-if="arrangements.length === 0" description="暂无特殊考生安排" />
          <div v-for="a in arrangements" :key="a.id" class="ios-row">
            <div class="ios-row-main">
              <div class="ios-row-title">{{ arrStudentName(a) }}</div>
              <div class="ios-row-sub">{{ a.arrangement_type }}{{ a.detail ? ` · ${a.detail}` : '' }}</div>
            </div>
            <template v-if="canManage">
              <n-button size="small" text type="primary" @click="openArrEdit(a)">编辑</n-button>
              <n-popconfirm @positive-click="removeArr(a)">
                <template #trigger><n-button size="small" text type="error">删除</n-button></template>
                确定删除这条特殊安排?
              </n-popconfirm>
            </template>
          </div>
        </div></div>
      </div>
    </template>

    <!-- 基本信息编辑 -->
    <n-modal v-model:show="showEdit" preset="card" title="编辑考试(仅草稿)" style="max-width: 480px">
      <n-space vertical>
        <n-text>考试名称</n-text>
        <n-input v-model:value="editForm.name" placeholder="考试名称" />
        <n-text>考试类型</n-text>
        <n-select v-model:value="editForm.exam_type" :options="typeOptions" />
        <n-text>参试年级(多选)</n-text>
        <n-select v-model:value="editForm.grades" :options="gradeOptions" multiple placeholder="选择参试年级" />
        <n-text>考试说明(选填)</n-text>
        <n-input v-model:value="editForm.description" type="textarea" placeholder="考试说明" />
        <n-button type="primary" @click="saveEdit">储存</n-button>
      </n-space>
    </n-modal>

    <!-- 状态回退:二次确认 + 备注留痕 -->
    <n-modal v-model:show="showBackward" preset="card" title="回退考试状态" style="max-width: 480px">
      <n-space vertical>
        <n-alert type="warning">回退是关键操作,须写备注留痕,回退后需重新按顺序推进。</n-alert>
        <n-text>回退到</n-text>
        <n-select v-model:value="backwardForm.to_status" :options="backwardOptions" />
        <n-text>回退备注(必填)</n-text>
        <n-input v-model:value="backwardForm.note" type="textarea" placeholder="写明回退原因" />
        <n-button type="primary" data-testid="exam-backward-confirm" @click="saveBackward">确认回退</n-button>
      </n-space>
    </n-modal>

    <!-- 参试个别增补 -->
    <n-modal v-model:show="showAddP" preset="card" title="个别增补参试学生" style="max-width: 480px">
      <n-space vertical>
        <n-text>学生(可多选)</n-text>
        <n-select v-model:value="addPForm.student_ids" :options="studentOptions" multiple filterable max-tag-count="responsive" placeholder="按姓名或学号选择学生(可多选)" data-testid="add-participant-students" />
        <n-text>备注(选填)</n-text>
        <n-input v-model:value="addPForm.note" type="textarea" placeholder="如:借读生" />
        <n-button type="primary" @click="saveAddP">增补</n-button>
      </n-space>
    </n-modal>

    <!-- 特殊安排登记/编辑 -->
    <n-modal v-model:show="showArr" preset="card" :title="editingArrId ? '编辑特殊安排' : '登记特殊安排'" style="max-width: 480px">
      <n-space vertical>
        <n-text>学生</n-text>
        <n-select v-model:value="arrForm.student_id" :options="studentOptions" filterable placeholder="按姓名或学号选择学生" />
        <n-text>安排类型</n-text>
        <n-select v-model:value="arrForm.arrangement_type" :options="arrTypeOptions" />
        <n-text>安排详情(选填)</n-text>
        <n-input v-model:value="arrForm.detail" type="textarea" placeholder="如:单独考场 201,延长 30 分钟" />
        <n-button type="primary" @click="saveArr">储存</n-button>
      </n-space>
    </n-modal>
  </div>
</template>
