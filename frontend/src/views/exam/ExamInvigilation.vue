<script setup lang="ts">
import {
  NAlert, NButton, NEmpty, NInput, NInputNumber, NModal, NPopconfirm,
  NSelect, NSpace, NSwitch, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import {
  DISCIPLINE_TYPES, INVIGILATION_ROLE, SHEET_VIEW_LABELS,
  addInvigilations, createDiscipline, createPatrol, deleteDiscipline, deleteInvigilation,
  deletePatrol, exportInvigilationWorkload, getExam, getInvigilationRule, getInvigilationSheet,
  getInvigilationWorkload, invigilateExam, listDiscipline, listExamRooms, listInvigilations,
  listInvigilators, listPatrols, listStudents, normalizeSheetView, saveInvigilationRule,
  saveInvigilators, toggleSheetView, updateDiscipline, updateInvigilation, updatePatrol,
} from '@/api/exam'
import type {
  Discipline, ExamDetail, ExamRoom, Invigilation, InvigilationRule, InvigilationSheetView,
  InvigilatorPoolItem, Patrol, RoomSheet, Student, TeacherSheet, WorkloadItem,
} from '@/api/exam'
import { listTeachers } from '@/api/basedata'
import type { Teacher } from '@/api/basedata'
import { classLabel } from '@/utils/labels'
import { useAuthStore } from '@/stores/auth'

const message = useMessage()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const examId = Number(route.params.id)
// 监考安排是教务职责:写操作只限 admin/director,越权时后端回 403,前端原样展示。
// 例外:考风考纪登记,监考教师本人也可登记本人监考场次的考生,后端把关。
const canManage = computed(() => auth.hasRole('admin') || auth.hasRole('director'))

const exam = ref<ExamDetail | null>(null)
const loading = ref(false)
const forbidden = ref(false)
const teachers = ref<Teacher[]>([])
const rooms = ref<ExamRoom[]>([])
const students = ref<Student[]>([])

const subjectOptions = computed(() => (exam.value?.subjects ?? []).map((s) => ({
  label: s.subject_name, value: s.subject_id,
})))
const teacherOptions = computed(() =>
  teachers.value.map((t) => ({ label: t.name, value: t.id })),
)
const roomOptions = computed(() =>
  rooms.value.map((r) => ({ label: r.room_name, value: r.room_id })),
)
const studentOptions = computed(() =>
  students.value.map((s) => ({ label: `${s.name}(${s.student_no}) ${classLabel({ grade: s.grade, name: s.class_name })}`, value: s.id })),
)

function goBack() {
  void router.push({ name: 'exam-exam-detail', params: { id: examId } })
}

// ── 监考规则与教师池(KW-23) ──
const rule = ref<InvigilationRule | null>(null)
const ruleForm = ref({ avoid_own_class: true, avoid_own_subject: true, invigilators_per_room: 2 })
const pool = ref<InvigilatorPoolItem[]>([])
async function reloadRule() {
  try {
    rule.value = await getInvigilationRule(examId)
    ruleForm.value = {
      avoid_own_class: rule.value.avoid_own_class,
      avoid_own_subject: rule.value.avoid_own_subject,
      invigilators_per_room: rule.value.invigilators_per_room,
    }
  } catch (e) {
    message.error((e as ApiError).detail || '监考规则加载失败')
  }
}
async function saveRule() {
  if (!exam.value) return
  try {
    rule.value = await saveInvigilationRule(exam.value.id, { ...ruleForm.value })
    message.success('监考规则已保存')
  } catch (e) {
    message.error((e as ApiError).detail || '保存失败')
  }
}
async function reloadPool() {
  try {
    pool.value = (await listInvigilators(examId)).items
  } catch (e) {
    message.error((e as ApiError).detail || '监考教师池加载失败')
  }
}
async function savePool() {
  if (!exam.value) return
  try {
    const res = await saveInvigilators(
      exam.value.id,
      pool.value.map((p) => ({ teacher_id: p.teacher_id, eligible: p.eligible })),
    )
    pool.value = res.items
    message.success(`监考教师池已保存,共 ${res.total} 人`)
  } catch (e) {
    message.error((e as ApiError).detail || '保存失败')
  }
}
// 教师池为空时(未建池),后端默认本学期全部在职教师可监考;下拉仍用全量教师。
const poolTeacherOptions = computed(() => {
  const eligible = pool.value.filter((p) => p.eligible)
  if (eligible.length) return eligible.map((p) => ({ label: p.teacher_name, value: p.teacher_id }))
  return teacherOptions.value
})

// ── 自动排监考(KW-24):一键排,可选科目;warnings 原样展示,绝不改写或隐藏 ──
const invigilateSubjectId = ref<number | null>(null)
const invigilating = ref(false)
const invigilateWarnings = ref<string[]>([])
const invigilateAssigned = ref<number | null>(null)
async function onInvigilate() {
  if (!exam.value) return
  invigilating.value = true
  invigilateWarnings.value = []
  invigilateAssigned.value = null
  try {
    const res = await invigilateExam(exam.value.id, invigilateSubjectId.value)
    // 后端返回的 warnings 全文原样展示,包括课表冲突与人选不足等警告。
    invigilateWarnings.value = res.warnings ?? []
    invigilateAssigned.value = res.assigned
    message.success(`已安排监考 ${res.assigned} 人次`)
    await Promise.all([reloadInvigilations(), reloadSheets(), reloadWorkload()])
  } catch (e) {
    message.error((e as ApiError).detail || '排监考失败')
  } finally {
    invigilating.value = false
  }
}

// ── 监考安排手工调整(KW-25):手工增删与替补换人 ──
const invigilations = ref<Invigilation[]>([])
const filterSubjectId = ref<number | null>(null)
const filterRoomId = ref<number | null>(null)
const filterTeacherId = ref<number | null>(null)
async function reloadInvigilations() {
  try {
    invigilations.value = (await listInvigilations(examId, {
      subjectId: filterSubjectId.value,
      roomId: filterRoomId.value,
      teacherId: filterTeacherId.value,
    })).items
  } catch (e) {
    message.error((e as ApiError).detail || '监考安排加载失败')
  }
}
const showAdd = ref(false)
const addForm = ref({ subject_id: null as number | null, room_id: null as number | null, teacher_ids: [] as number[] })
function openAdd() {
  addForm.value = { subject_id: null, room_id: null, teacher_ids: [] }
  showAdd.value = true
}
async function saveAdd() {
  if (!exam.value) return
  if (!addForm.value.subject_id || !addForm.value.room_id || !addForm.value.teacher_ids.length) {
    message.warning('请先选择科目、考场和监考教师')
    return
  }
  try {
    const res = await addInvigilations(exam.value.id, {
      subject_id: addForm.value.subject_id,
      room_id: addForm.value.room_id,
      teacher_ids: addForm.value.teacher_ids,
      role: INVIGILATION_ROLE,
    })
    showAdd.value = false
    message.success(res.skipped > 0
      ? `监考安排已添加 ${res.created} 人次,跳过 ${res.skipped} 人次(已安排或冲突)`
      : `监考安排已添加 ${res.created} 人次`)
    await Promise.all([reloadInvigilations(), reloadSheets(), reloadWorkload()])
  } catch (e) {
    message.error((e as ApiError).detail || '添加失败')
  }
}
const showReplace = ref(false)
const replaceTarget = ref<Invigilation | null>(null)
const replaceTeacherId = ref<number | null>(null)
function openReplace(row: Invigilation) {
  replaceTarget.value = row
  replaceTeacherId.value = null
  showReplace.value = true
}
async function saveReplace() {
  if (!exam.value || !replaceTarget.value) return
  if (!replaceTeacherId.value) { message.warning('请选择替补教师'); return }
  try {
    await updateInvigilation(exam.value.id, replaceTarget.value.id, {
      teacher_id: replaceTeacherId.value,
    })
    showReplace.value = false
    message.success('已换为替补教师')
    await Promise.all([reloadInvigilations(), reloadSheets(), reloadWorkload()])
  } catch (e) {
    message.error((e as ApiError).detail || '换人失败')
  }
}
async function removeInvigilation(row: Invigilation) {
  if (!exam.value) return
  try {
    await deleteInvigilation(exam.value.id, row.id)
    message.success('监考安排已删除')
    await Promise.all([reloadInvigilations(), reloadSheets(), reloadWorkload()])
  } catch (e) {
    message.error((e as ApiError).detail || '删除失败')
  }
}
// ── 监考表两视图(KW-27) ──
const sheetView = ref<InvigilationSheetView>('teacher')
const sheetSubjectId = ref<number | null>(null)
const teacherSheet = ref<TeacherSheet | null>(null)
const roomSheet = ref<RoomSheet | null>(null)
async function reloadSheets() {
  try {
    const res = await getInvigilationSheet(examId, sheetView.value, sheetSubjectId.value)
    if (sheetView.value === 'room') {
      roomSheet.value = res as RoomSheet
      teacherSheet.value = null
    } else {
      teacherSheet.value = res as TeacherSheet
      roomSheet.value = null
    }
  } catch (e) {
    message.error((e as ApiError).detail || '监考表加载失败')
  }
}
function setSheetView(view: string) {
  sheetView.value = normalizeSheetView(view)
  void reloadSheets()
}
function onSheetViewToggle() {
  sheetView.value = toggleSheetView(sheetView.value)
  void reloadSheets()
}
// 打印(KW-27):照抄现有打印页做法,@media print + window.print,
// 用户用浏览器“另存为 PDF”得到 PDF;只打印监考表分区,其余分区隐藏。
function doPrint() {
  window.print()
}

// ── 巡考安排(KW-26) ──
const patrols = ref<Patrol[]>([])
async function reloadPatrols() {
  try {
    patrols.value = (await listPatrols(examId)).items
  } catch (e) {
    message.error((e as ApiError).detail || '巡考安排加载失败')
  }
}
const showPatrol = ref(false)
const editingPatrolId = ref<number | null>(null)
const patrolForm = ref({ exam_date: '', teacher_id: null as number | null, scope: '', note: '' })
function openPatrolCreate() {
  editingPatrolId.value = null
  patrolForm.value = { exam_date: '', teacher_id: null, scope: '', note: '' }
  showPatrol.value = true
}
function openPatrolEdit(p: Patrol) {
  editingPatrolId.value = p.id
  patrolForm.value = {
    exam_date: p.exam_date ?? '', teacher_id: p.teacher_id,
    scope: p.scope ?? '', note: p.note ?? '',
  }
  showPatrol.value = true
}
async function savePatrol() {
  if (!exam.value) return
  if (!patrolForm.value.exam_date || !patrolForm.value.teacher_id || !patrolForm.value.scope.trim()) {
    message.warning('请先填写巡考日期、巡考教师与负责范围')
    return
  }
  try {
    const body = {
      exam_date: patrolForm.value.exam_date,
      teacher_id: patrolForm.value.teacher_id,
      scope: patrolForm.value.scope.trim(),
      note: patrolForm.value.note.trim() || null,
    }
    if (editingPatrolId.value) await updatePatrol(exam.value.id, editingPatrolId.value, body)
    else await createPatrol(exam.value.id, body)
    showPatrol.value = false
    message.success('巡考安排已保存')
    await reloadPatrols()
  } catch (e) {
    message.error((e as ApiError).detail || '保存失败')
  }
}
async function removePatrol(p: Patrol) {
  if (!exam.value) return
  try {
    await deletePatrol(exam.value.id, p.id)
    message.success('巡考安排已删除')
    await reloadPatrols()
  } catch (e) {
    message.error((e as ApiError).detail || '删除失败')
  }
}

// ── 监考工作量统计(KW-28):只出场次与分钟数,不折算补贴 ──
const workload = ref<WorkloadItem[]>([])
const workloadTotal = ref(0)
async function reloadWorkload() {
  try {
    const res = await getInvigilationWorkload(examId)
    workload.value = res.items
    workloadTotal.value = res.total
  } catch (e) {
    message.error((e as ApiError).detail || '监考工作量加载失败')
  }
}
async function onExportWorkload() {
  if (!exam.value) return
  try {
    await exportInvigilationWorkload(exam.value.id)
    message.success('监考工作量表已开始下载')
  } catch (e) {
    message.error((e as ApiError).detail || '导出失败')
  }
}

// ── 考风考纪记录(KW-29) ──
const disciplines = ref<Discipline[]>([])
async function reloadDiscipline() {
  try {
    disciplines.value = (await listDiscipline(examId)).items
  } catch (e) {
    message.error((e as ApiError).detail || '考风考纪记录加载失败')
  }
}
const showDiscipline = ref(false)
const editingDisciplineId = ref<number | null>(null)
const disciplineForm = ref({
  subject_id: null as number | null, student_id: null as number | null,
  type: '违纪' as string, description: '', handling: '',
})
const disciplineTypeOptions = DISCIPLINE_TYPES.map((t) => ({ label: t, value: t }))
function openDisciplineCreate() {
  editingDisciplineId.value = null
  disciplineForm.value = { subject_id: null, student_id: null, type: '违纪', description: '', handling: '' }
  showDiscipline.value = true
}
function openDisciplineEdit(d: Discipline) {
  editingDisciplineId.value = d.id
  disciplineForm.value = {
    subject_id: d.subject_id, student_id: d.student_id, type: d.type,
    description: d.description ?? '', handling: d.handling ?? '',
  }
  showDiscipline.value = true
}
async function saveDiscipline() {
  if (!exam.value) return
  if (!disciplineForm.value.subject_id || !disciplineForm.value.student_id) {
    message.warning('请先选择科目与学生')
    return
  }
  try {
    const body = {
      subject_id: disciplineForm.value.subject_id,
      student_id: disciplineForm.value.student_id,
      type: disciplineForm.value.type,
      description: disciplineForm.value.description.trim() || null,
      handling: disciplineForm.value.handling.trim() || null,
    }
    if (editingDisciplineId.value) await updateDiscipline(exam.value.id, editingDisciplineId.value, body)
    else await createDiscipline(exam.value.id, body)
    showDiscipline.value = false
    message.success('考风考纪记录已保存')
    await reloadDiscipline()
  } catch (e) {
    message.error((e as ApiError).detail || '保存失败')
  }
}
async function removeDiscipline(d: Discipline) {
  if (!exam.value) return
  try {
    await deleteDiscipline(exam.value.id, d.id)
    message.success('考风考纪记录已删除')
    await reloadDiscipline()
  } catch (e) {
    message.error((e as ApiError).detail || '删除失败')
  }
}

async function reload() {
  loading.value = true
  forbidden.value = false
  try {
    exam.value = await getExam(examId)
    const sid = exam.value.semester_id
    const [teacherList, studentList] = await Promise.all([
      listTeachers(sid),
      listStudents({ semesterId: sid, limit: 100 }),
    ])
    teachers.value = teacherList
    students.value = studentList.items
    rooms.value = (await listExamRooms(examId)).items
    await Promise.all([
      reloadRule(), reloadPool(), reloadInvigilations(),
      reloadSheets(), reloadPatrols(), reloadWorkload(), reloadDiscipline(),
    ])
  } catch (e) {
    if ((e as ApiError).status === 403) forbidden.value = true
    else message.error((e as ApiError).detail || '加载失败')
  } finally {
    loading.value = false
  }
}
onMounted(() => { void reload() })
</script>

<template>
  <div class="ios-page">
    <div class="no-print" style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap">
      <n-button text type="primary" @click="goBack">← 考试详情</n-button>
      <h1 class="ios-title">{{ exam?.name ? `${exam.name} · 监考安排` : '监考安排' }}</h1>
    </div>

    <n-alert v-if="forbidden" type="error" style="margin-top: 16px" class="no-print">
      无权查看该考试(不在你的可见范围内)。
    </n-alert>
    <n-empty v-else-if="!loading && !exam" description="找不到该考试" style="margin-top: 24px" class="no-print" />

    <template v-else-if="exam">
      <!-- 监考规则与教师池(KW-23) -->
      <div class="ios-section no-print">
        <div class="ios-section-title">监考规则与教师池</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            回避规则默认班主任避监本班、任课教师避监本学科均开,每考场监考人数默认 2 人;
            回避口径与每考场人数仍待学校确认。教师池停用的教师不参与自动排监考。
          </n-text>
          <n-space vertical>
            <n-space align="center">
              <n-text style="font-size: 13px">班主任避监本班</n-text>
              <n-switch v-model:value="ruleForm.avoid_own_class" :disabled="!canManage" />
              <n-text style="font-size: 13px">任课教师避监本学科</n-text>
              <n-switch v-model:value="ruleForm.avoid_own_subject" :disabled="!canManage" />
              <n-text style="font-size: 13px">每考场监考人数</n-text>
              <n-input-number
                v-model:value="ruleForm.invigilators_per_room" :min="1" :disabled="!canManage"
                placeholder="每考场人数" style="width: 120px"
              />
              <n-button type="primary" :disabled="!canManage" data-testid="invigilation-save-rule" @click="saveRule">保存监考规则</n-button>
            </n-space>
            <n-empty v-if="pool.length === 0" description="尚未建立教师池,默认本学期全部在职教师可监考" />
            <table v-else class="ios-table">
              <thead><tr><th>教师</th><th>是否可监考</th></tr></thead>
              <tbody>
                <tr v-for="p in pool" :key="p.teacher_id">
                  <td>{{ p.teacher_name }}</td>
                  <td>
                    <n-switch v-model:value="p.eligible" :disabled="!canManage" />
                    {{ p.eligible ? '可监考' : '已停用' }}
                  </td>
                </tr>
              </tbody>
            </table>
            <n-button
              v-if="pool.length" type="primary" :disabled="!canManage"
              data-testid="invigilation-save-pool" @click="savePool"
            >保存教师池</n-button>
          </n-space>
        </div></div>
      </div>

      <!-- 自动排监考(KW-24) -->
      <div class="ios-section no-print">
        <div class="ios-section-title">自动排监考</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            按场次为每考场自动安排监考教师,均衡每位教师总场次,并检测与课表、已有监考的时间冲突;
            已排过的不重复排,只补足缺额。角色统一为“监考”,不区分主监与副监。
          </n-text>
          <n-space :wrap="true" align="center">
            <n-select
              v-model:value="invigilateSubjectId" :options="subjectOptions" clearable
              placeholder="全部科目" style="width: 160px" :disabled="!canManage"
            />
            <n-button
              type="primary" :disabled="!canManage" :loading="invigilating"
              data-testid="invigilate-run" @click="onInvigilate"
            >一键自动排监考</n-button>
          </n-space>
          <n-alert
            v-if="invigilateAssigned !== null" type="success" style="margin-top: 12px"
            data-testid="invigilate-result"
          >
            已安排监考 {{ invigilateAssigned }} 人次。
          </n-alert>
          <!-- warnings 原样展示:后端返回什么文案就显示什么,不得改写、省略或合并 -->
          <n-alert
            v-if="invigilateWarnings.length" type="warning" style="margin-top: 12px"
            data-testid="invigilate-warnings"
          >
            <div v-for="(w, i) in invigilateWarnings" :key="i">{{ w }}</div>
          </n-alert>
        </div></div>
      </div>

      <!-- 监考安排手工调整(KW-25) -->
      <div class="ios-section no-print">
        <div class="ios-section-title">监考安排 · 手工调整与替补</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-space :wrap="true" align="center">
            <n-select
              v-model:value="filterSubjectId" :options="subjectOptions" clearable
              placeholder="全部科目" style="width: 150px" @update:value="reloadInvigilations"
            />
            <n-select
              v-model:value="filterRoomId" :options="roomOptions" clearable
              placeholder="全部考场" style="width: 150px" @update:value="reloadInvigilations"
            />
            <n-select
              v-model:value="filterTeacherId" :options="teacherOptions" clearable
              placeholder="全部教师" style="width: 150px" @update:value="reloadInvigilations"
            />
            <n-button @click="reloadInvigilations">检索</n-button>
            <n-button v-if="canManage" type="primary" data-testid="invigilation-add" @click="openAdd">手工添加监考</n-button>
          </n-space>
          <n-empty v-if="invigilations.length === 0" description="暂无监考安排,请先自动排监考或手工添加" style="margin-top: 12px" />
          <table v-else class="ios-table" style="margin-top: 12px">
            <thead><tr><th>科目</th><th>考场</th><th>监考教师</th><th>角色</th><th v-if="canManage">操作</th></tr></thead>
            <tbody>
              <tr v-for="row in invigilations" :key="row.id">
                <td>{{ row.subject_name }}</td>
                <td>{{ row.room_name }}</td>
                <td>{{ row.teacher_name }}</td>
                <td>{{ row.role || INVIGILATION_ROLE }}</td>
                <td v-if="canManage">
                  <n-space size="small" :wrap="false">
                    <n-button size="small" text type="primary" data-testid="invigilation-replace" @click="openReplace(row)">替补换人</n-button>
                    <n-popconfirm @positive-click="removeInvigilation(row)">
                      <template #trigger><n-button size="small" text type="error">删除</n-button></template>
                      确定删除这条监考安排?
                    </n-popconfirm>
                  </n-space>
                </td>
              </tr>
            </tbody>
          </table>
          <n-text depth="3" style="font-size: 12px; display: block; margin-top: 8px">
            教师临时请假时用“替补换人”快速换人,调整结果即时同步到监考表与工作量统计。
          </n-text>
        </div></div>
      </div>

      <!-- 监考表两视图打印(KW-27):打印区只留本分区,其余分区在打印时隐藏 -->
      <div class="ios-section print-area">
        <div class="ios-section-title no-print">监考表</div>
        <div class="no-print" style="margin-bottom: 12px">
          <n-space :wrap="true" align="center">
            <n-button
              :type="sheetView === 'teacher' ? 'primary' : 'default'"
              data-testid="sheet-view-teacher" @click="setSheetView('teacher')"
            >{{ SHEET_VIEW_LABELS.teacher }}</n-button>
            <n-button
              :type="sheetView === 'room' ? 'primary' : 'default'"
              data-testid="sheet-view-room" @click="setSheetView('room')"
            >{{ SHEET_VIEW_LABELS.room }}</n-button>
            <n-button data-testid="sheet-view-toggle" @click="onSheetViewToggle">切换视图</n-button>
            <n-select
              v-model:value="sheetSubjectId" :options="subjectOptions" clearable
              placeholder="全部科目" style="width: 150px" @update:value="reloadSheets"
            />
            <n-button type="primary" data-testid="invigilation-sheet-print" @click="doPrint">打印</n-button>
            <n-text depth="3" style="font-size: 12px">
              打印当前视图,用浏览器“另存为 PDF”得到 PDF。
            </n-text>
          </n-space>
        </div>
        <h1 class="sheet-head">{{ exam.name }} · 监考表({{ SHEET_VIEW_LABELS[sheetView] }})</h1>
        <template v-if="sheetView === 'teacher'">
          <n-empty
            v-if="!teacherSheet || teacherSheet.teachers.length === 0"
            description="暂无监考表,请先自动排监考或手工添加" data-testid="sheet-teacher-empty"
          />
          <div
            v-for="t in teacherSheet?.teachers ?? []" :key="t.teacher_id"
            class="sheet-block" data-testid="sheet-teacher-block"
          >
            <div class="sheet-subhead">教师:{{ t.teacher_name }}(共 {{ t.sessions.length }} 场)</div>
            <table class="sheet-grid">
              <thead><tr><th>科目</th><th>考试日期</th><th>开始时间</th><th>结束时间</th><th>考场</th></tr></thead>
              <tbody>
                <tr v-for="(s, i) in t.sessions" :key="i">
                  <td>{{ s.subject_name }}</td>
                  <td>{{ s.exam_date }}</td>
                  <td>{{ s.start_time }}</td>
                  <td>{{ s.end_time }}</td>
                  <td>{{ s.room_name }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
        <template v-else>
          <n-empty
            v-if="!roomSheet || roomSheet.rooms.length === 0"
            description="暂无监考表,请先自动排监考或手工添加" data-testid="sheet-room-empty"
          />
          <div
            v-for="r in roomSheet?.rooms ?? []" :key="r.room_id"
            class="sheet-block" data-testid="sheet-room-block"
          >
            <div class="sheet-subhead">考场:{{ r.room_name }}</div>
            <table class="sheet-grid">
              <thead><tr><th>科目</th><th>考试日期</th><th>开始时间</th><th>结束时间</th><th>监考教师</th></tr></thead>
              <tbody>
                <tr v-for="(s, i) in r.sessions" :key="i">
                  <td>{{ s.subject_name }}</td>
                  <td>{{ s.exam_date }}</td>
                  <td>{{ s.start_time }}</td>
                  <td>{{ s.end_time }}</td>
                  <td>{{ s.teachers.join('、') }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </div>

      <!-- 巡考安排(KW-26) -->
      <div class="ios-section no-print">
        <div class="ios-section-title">巡考安排</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-button v-if="canManage" style="margin-bottom: 12px" data-testid="patrol-add" @click="openPatrolCreate">安排巡考</n-button>
          <n-empty v-if="patrols.length === 0" description="暂无巡考安排" />
          <div v-for="p in patrols" :key="p.id" class="ios-row">
            <div class="ios-row-main">
              <div class="ios-row-title">{{ p.teacher_name }} · {{ p.exam_date }}</div>
              <div class="ios-row-sub">负责范围:{{ p.scope }}{{ p.note ? ` · ${p.note}` : '' }}</div>
            </div>
            <template v-if="canManage">
              <n-button size="small" text type="primary" @click="openPatrolEdit(p)">编辑</n-button>
              <n-popconfirm @positive-click="removePatrol(p)">
                <template #trigger><n-button size="small" text type="error">删除</n-button></template>
                确定删除这条巡考安排?
              </n-popconfirm>
            </template>
          </div>
        </div></div>
      </div>

      <!-- 考风考纪记录(KW-29) -->
      <div class="ios-section no-print">
        <div class="ios-section-title">考风考纪记录</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            监考教师登记违纪与作弊事件,教务汇总;是否记入学生档案与德育评价,仍待学校确认。
          </n-text>
          <n-button style="margin-bottom: 12px" data-testid="discipline-add" @click="openDisciplineCreate">登记违纪/作弊</n-button>
          <n-empty v-if="disciplines.length === 0" description="暂无考风考纪记录" />
          <div v-for="d in disciplines" :key="d.id" class="ios-row">
            <div class="ios-row-main">
              <div class="ios-row-title">{{ d.student_name }}({{ d.student_no }}) {{ classLabel({ grade: d.grade, name: d.class_name }) }} · {{ d.type }}</div>
              <div class="ios-row-sub">
                {{ d.subject_name }}{{ d.description ? ` · ${d.description}` : '' }}{{ d.handling ? ` · 处理:${d.handling}` : '' }}
                {{ d.recorded_by_name ? ` · 登记人:${d.recorded_by_name}` : '' }}
              </div>
            </div>
            <template v-if="canManage">
              <n-button size="small" text type="primary" @click="openDisciplineEdit(d)">编辑</n-button>
              <n-popconfirm @positive-click="removeDiscipline(d)">
                <template #trigger><n-button size="small" text type="error">删除</n-button></template>
                确定删除这条考风考纪记录?
              </n-popconfirm>
            </template>
          </div>
        </div></div>
      </div>

      <!-- 监考工作量统计(KW-28) -->
      <div class="ios-section no-print">
        <div class="ios-section-title">监考工作量统计</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            只统计每位教师监考场次与时长(分钟),不折算补贴、不与课时统计合并;
            导出供绩效与补贴核算参考,是否折算补贴由学校定口径。
          </n-text>
          <n-space :wrap="true" align="center" style="margin-bottom: 12px">
            <n-button data-testid="workload-export" @click="onExportWorkload">导出工作量表</n-button>
            <n-text depth="3" style="font-size: 13px">共 {{ workloadTotal }} 人</n-text>
          </n-space>
          <n-empty v-if="workload.length === 0" description="暂无监考工作量" />
          <table v-else class="ios-table">
            <thead><tr><th>教师</th><th>监考场次</th><th>总时长(分钟)</th></tr></thead>
            <tbody>
              <tr v-for="w in workload" :key="w.teacher_id">
                <td>{{ w.teacher_name }}</td>
                <td>{{ w.sessions }}</td>
                <td>{{ w.minutes }}</td>
              </tr>
            </tbody>
          </table>
        </div></div>
      </div>
    </template>

    <!-- 手工添加监考 -->
    <n-modal v-model:show="showAdd" preset="card" title="手工添加监考" style="max-width: 480px">
      <n-space vertical>
        <n-text>科目</n-text>
        <n-select v-model:value="addForm.subject_id" :options="subjectOptions" placeholder="选择科目" />
        <n-text>考场</n-text>
        <n-select v-model:value="addForm.room_id" :options="roomOptions" placeholder="选择考场" />
        <n-text>监考教师</n-text>
        <n-select
          v-model:value="addForm.teacher_ids" :options="poolTeacherOptions" filterable multiple
          max-tag-count="responsive" placeholder="选择监考教师(可多选)"
        />
        <n-text depth="3" style="font-size: 12px">角色统一为“监考”,不区分主监与副监。</n-text>
        <n-button type="primary" @click="saveAdd">确认添加</n-button>
      </n-space>
    </n-modal>

    <!-- 替补换人 -->
    <n-modal v-model:show="showReplace" preset="card" title="替补换人" style="max-width: 480px">
      <n-space vertical>
        <n-text>原监考:{{ replaceTarget?.teacher_name }} · {{ replaceTarget?.subject_name }} {{ replaceTarget?.room_name }}</n-text>
        <n-text>替补教师</n-text>
        <n-select v-model:value="replaceTeacherId" :options="poolTeacherOptions" filterable placeholder="选择替补教师" />
        <n-button type="primary" @click="saveReplace">确认换人</n-button>
      </n-space>
    </n-modal>

    <!-- 巡考登记/编辑 -->
    <n-modal v-model:show="showPatrol" preset="card" :title="editingPatrolId ? '编辑巡考安排' : '安排巡考'" style="max-width: 480px">
      <n-space vertical>
        <n-text>巡考日期</n-text>
        <input v-model="patrolForm.exam_date" type="date" style="width: 170px">
        <n-text>巡考教师</n-text>
        <n-select v-model:value="patrolForm.teacher_id" :options="teacherOptions" filterable placeholder="选择巡考教师" />
        <n-text>负责范围(楼层/考场)</n-text>
        <n-input v-model:value="patrolForm.scope" placeholder="如:二楼 201-206 考场" />
        <n-text>备注(选填)</n-text>
        <n-input v-model:value="patrolForm.note" type="textarea" placeholder="备注" />
        <n-button type="primary" @click="savePatrol">储存</n-button>
      </n-space>
    </n-modal>

    <!-- 考风考纪登记/编辑 -->
    <n-modal v-model:show="showDiscipline" preset="card" :title="editingDisciplineId ? '编辑考风考纪记录' : '登记违纪/作弊'" style="max-width: 480px">
      <n-space vertical>
        <n-text>科目</n-text>
        <n-select v-model:value="disciplineForm.subject_id" :options="subjectOptions" placeholder="选择科目" />
        <n-text>学生</n-text>
        <n-select v-model:value="disciplineForm.student_id" :options="studentOptions" filterable placeholder="按姓名或学号选择学生" />
        <n-text>类型</n-text>
        <n-select v-model:value="disciplineForm.type" :options="disciplineTypeOptions" />
        <n-text>事件描述(选填)</n-text>
        <n-input v-model:value="disciplineForm.description" type="textarea" placeholder="如:考试中查看手机" />
        <n-text>处理结果(选填)</n-text>
        <n-input v-model:value="disciplineForm.handling" type="textarea" placeholder="如:取消该科成绩" />
        <n-button type="primary" @click="saveDiscipline">储存</n-button>
      </n-space>
    </n-modal>
  </div>
</template>

<style scoped>
.sheet-head { text-align: center; font-size: 19px; font-weight: 600; letter-spacing: 2px; margin: 0 0 16px; }
.sheet-block { margin-bottom: 24px; page-break-inside: avoid; }
.sheet-subhead { font-size: 15px; font-weight: 600; margin-bottom: 8px; }
.sheet-grid { border-collapse: collapse; width: 100%; table-layout: fixed; font-size: 13px; }
.sheet-grid th, .sheet-grid td { border: 1px solid #000; padding: 5px 6px; text-align: center; }
.sheet-grid th { background: #eee; }

@media print {
  @page { size: A4 portrait; margin: 12mm; }
  .no-print { display: none !important; }
  .print-area { max-width: none; padding: 0; }
  .sheet-block { break-inside: avoid; page-break-inside: avoid; }
}
</style>

<style>
/* 打印页套在 MainLayout 内:打印时隐藏侧边栏与顶栏,只留监考表分区。 */
@media print {
  .n-layout-sider, .app-header { display: none !important; }
}
</style>
