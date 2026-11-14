// 考务地基 API(KW-01~07):学生档案、导入导出、异动、家长、学科分值、考号规则。
// 以 backend/app/api/exam_students.py 与 backend/app/schemas/exam_students.py 为准,
// 全部走 /api/exam。写接口权限以后端为准:学生写操作只限 admin/director,
// 家长写操作班主任可改本班、教务可改全校,学科分值 PUT 允许 admin/director 全改、
// 教研组长只改本科目(逐科由后端 403 拦截,前端不假装有权限)。

import { apiDelete, apiGet, apiPost, apiPut, request } from '@/api/client'
import type { ApiError } from '@/api/client'

export type { ApiError }

export interface Parent {
  id: number
  name: string
  relation: string | null
  phone: string | null
}

export interface Student {
  id: number
  semester_id: number
  class_unit_id: number
  class_name: string
  grade: number | null
  student_no: string
  name: string
  gender: string | null
  status: string
  exam_no: string | null
  parents: Parent[]
}

export interface StudentList {
  items: Student[]
  total: number
}

export interface StatusChange {
  id: number
  student_id: number
  change_type: string
  from_class_unit_id: number | null
  to_class_unit_id: number | null
  from_class_name: string | null
  to_class_name: string | null
  from_status: string | null
  to_status: string | null
  note: string | null
  changed_by: number | null
  created_at: string | null
}

export interface ImportResult {
  created: number
  updated: number
  errors: string[]
}

export interface SubjectSetting {
  subject_id: number
  subject_name: string
  full_score: number
  pass_line: number
  excellent_line: number
  counts_toward_total: boolean
  conversion_ratio: number
}

export interface ExamNumberRule {
  semester_id: number
  grade: number | null
  rule_type: string
}

export interface ExamNumberGenerateResult {
  generated: number
  warning: string
}

// 后端枚举(backend/app/models/exam_foundation.py):状态只有在读/休学/毕业,
// 转班不是状态,是异动类型。
export const STUDENT_STATUSES = ['在读', '休学', '毕业'] as const
export const CHANGE_TYPES = ['转班', '休学', '复学', '毕业', '入学'] as const
export const RULE_TYPES = ['by_student_no', 'sequential', 's_shape'] as const

export const RULE_TYPE_LABELS: Record<string, string> = {
  by_student_no: '按学号直接使用',
  sequential: '按年级流水编排',
  s_shape: '按上次成绩 S 型编排',
}

/** 未设置科目的默认值(与后端 DEFAULT_SETTING 一致)。 */
export const DEFAULT_SUBJECT_SETTING = {
  full_score: 100,
  pass_line: 60,
  excellent_line: 85,
  counts_toward_total: true,
  conversion_ratio: 1.0,
}

/** S 型无成绩警告:后端原样返回,前端必须原样展示,不得改写或省略。 */
export const S_SHAPE_NO_SCORE_WARNING = '暂无上次成绩，暂按学号顺序编排'

/** 家长电话脱敏(与后端 mask_phone 同规则):13812345678 -> 138****5678。 */
export function maskPhone(phone: string | null | undefined): string | null {
  if (!phone) return phone ?? null
  const p = phone.trim()
  if (p.length >= 7) return `${p.slice(0, 3)}****${p.slice(-4)}`
  if (p.length > 4) return `${p.slice(0, 2)}****${p.slice(-2)}`
  return '****'
}

export interface ListStudentsParams {
  semesterId: number
  grade?: number | null
  classUnitId?: number | null
  q?: string
  status?: string | null
  limit?: number
  offset?: number
}

export function listStudents(params: ListStudentsParams): Promise<StudentList> {
  const qs = new URLSearchParams({ semester_id: String(params.semesterId) })
  if (params.grade != null) qs.set('grade', String(params.grade))
  if (params.classUnitId != null) qs.set('class_unit_id', String(params.classUnitId))
  if (params.q) qs.set('q', params.q)
  if (params.status) qs.set('status', params.status)
  qs.set('limit', String(params.limit ?? 100))
  qs.set('offset', String(params.offset ?? 0))
  return apiGet<StudentList>(`/exam/students?${qs.toString()}`)
}

export const getStudent = (id: number) => apiGet<Student>(`/exam/students/${id}`)

export function createStudent(body: {
  semester_id: number
  class_unit_id: number
  student_no: string
  name: string
  gender?: string | null
  status?: string
  exam_no?: string | null
}): Promise<Student> {
  return apiPost<Student>('/exam/students', body)
}

export function updateStudent(
  id: number,
  body: { name?: string | null; gender?: string | null; class_unit_id?: number | null },
): Promise<Student> {
  return request<Student>('PATCH', `/exam/students/${id}`, body)
}

export function changeStudentStatus(
  id: number,
  body: {
    to_status: string
    note?: string | null
    new_class_unit_id?: number | null
    change_type?: string | null
  },
): Promise<Student> {
  return apiPost<Student>(`/exam/students/${id}/status`, body)
}

export const listStatusChanges = (studentId: number) =>
  apiGet<{ items: StatusChange[] }>(`/exam/students/${studentId}/status-changes`)

export const listParents = (studentId: number) =>
  apiGet<Parent[]>(`/exam/students/${studentId}/parents`)

export function createParent(
  studentId: number,
  body: { name: string; relation?: string | null; phone?: string | null },
): Promise<Parent> {
  return apiPost<Parent>(`/exam/students/${studentId}/parents`, body)
}

export function updateParent(
  parentId: number,
  body: { name: string; relation?: string | null; phone?: string | null },
): Promise<Parent> {
  return request<Parent>('PATCH', `/exam/parents/${parentId}`, body)
}

export function deleteParent(parentId: number): Promise<void> {
  return request<void>('DELETE', `/exam/parents/${parentId}`)
}

async function downloadBlob(path: string, fallbackName: string): Promise<void> {
  const resp = await fetch(`/api${path}`, { credentials: 'include' })
  if (!resp.ok) {
    let detail: string | undefined
    try {
      detail = (await resp.json())?.detail
    } catch {
      detail = undefined
    }
    throw new Error(detail || `下载失败(${resp.status})`)
  }
  const blob = await resp.blob()
  const cd = resp.headers.get('Content-Disposition')
  const m = cd ? /filename="([^"]+)"/.exec(cd) : null
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = m ? m[1] : fallbackName
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export const downloadStudentTemplate = () =>
  downloadBlob('/exam/students/template', 'students_template.xlsx')

export function exportStudents(
  semesterId: number,
  grade?: number | null,
  classUnitId?: number | null,
): Promise<void> {
  const qs = new URLSearchParams({ semester_id: String(semesterId) })
  if (grade != null) qs.set('grade', String(grade))
  if (classUnitId != null) qs.set('class_unit_id', String(classUnitId))
  return downloadBlob(`/exam/students/export?${qs.toString()}`, 'students_export.xlsx')
}

/** 上传 Excel 导入:回传新增/更新笔数与逐行错误(错误行不入库,正确行照常入库)。 */
export async function importStudents(semesterId: number, file: File): Promise<ImportResult> {
  const form = new FormData()
  form.append('file', file)
  const resp = await fetch(`/api/exam/students/import?semester_id=${semesterId}`, {
    method: 'POST',
    credentials: 'include',
    body: form,
  })
  if (!resp.ok) {
    let detail = '导入失败'
    try {
      detail = (await resp.json())?.detail ?? detail
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return resp.json() as Promise<ImportResult>
}

// ── 学科分值(KW-06) ──
export const listSubjectSettings = (semesterId: number) =>
  apiGet<{ items: SubjectSetting[] }>(`/exam/subject-settings?semester_id=${semesterId}`)

export function saveSubjectSettings(
  semesterId: number,
  settings: SubjectSetting[],
): Promise<{ items: SubjectSetting[] }> {
  return apiPut<{ items: SubjectSetting[] }>('/exam/subject-settings', {
    semester_id: semesterId,
    settings: settings.map((s) => ({
      subject_id: s.subject_id,
      full_score: s.full_score,
      pass_line: s.pass_line,
      excellent_line: s.excellent_line,
      counts_toward_total: s.counts_toward_total,
      conversion_ratio: s.conversion_ratio,
    })),
  })
}

// ── 考号规则(KW-07) ──
export function getExamNumberRule(
  semesterId: number,
  grade?: number | null,
): Promise<ExamNumberRule> {
  const qs = new URLSearchParams({ semester_id: String(semesterId) })
  if (grade != null) qs.set('grade', String(grade))
  return apiGet<ExamNumberRule>(`/exam/exam-number-rule?${qs.toString()}`)
}

export function saveExamNumberRule(
  semesterId: number,
  grade: number | null,
  ruleType: string,
): Promise<ExamNumberRule> {
  return apiPut<ExamNumberRule>('/exam/exam-number-rule', {
    semester_id: semesterId,
    grade,
    rule_type: ruleType,
  })
}

export function generateExamNumbers(
  semesterId: number,
  grade: number,
): Promise<ExamNumberGenerateResult> {
  return apiPost<ExamNumberGenerateResult>('/exam/exam-number-rule/generate', {
    semester_id: semesterId,
    grade,
  })
}

// ── 考试管理(KW-08~14) ──
// 契约见任务书(与后端切片共用):状态与类型枚举以后端为准,前端只做展示与流转,
// 不自行增删枚举值。考试类型清单、日程冲突是否阻断、状态节点名称、
// 特殊考生隐私范围四项口径仍待学校确认,见汇报。
export const EXAM_STATUSES = ['草稿', '已发布', '进行中', '成绩处理中', '已发布成绩', '已归档'] as const
export type ExamStatus = (typeof EXAM_STATUSES)[number]
export const EXAM_TYPES = ['周测', '月考', '期中', '期末', '模拟考', '联考'] as const
export type ExamType = (typeof EXAM_TYPES)[number]
export const PARTICIPANT_STATUSES = ['正常', '缺考', '免考'] as const
export type ParticipantStatus = (typeof PARTICIPANT_STATUSES)[number]
export const ARRANGEMENT_TYPES = ['单独考场', '延长时限', '放大字号试卷', '其他'] as const
export type ArrangementType = (typeof ARRANGEMENT_TYPES)[number]

export interface ExamSubject {
  subject_id: number
  subject_name: string
  exam_date: string | null
  start_time: string | null
  end_time: string | null
  full_score: number | null
}

export interface Exam {
  id: number
  semester_id: number
  name: string
  exam_type: string
  grades: number[]
  status: string
  description: string | null
  created_at: string | null
}

export interface ExamDetail extends Exam {
  subjects: ExamSubject[]
  participant_count: number
}

export interface ExamList {
  items: Exam[]
  total: number
}

export interface ExamParticipant {
  id: number
  exam_id: number
  student_id: number
  student_no: string
  student_name: string
  class_unit_id: number | null
  class_name: string | null
  grade: number | null
  status: string
  note: string | null
}

export interface ParticipantList {
  items: ExamParticipant[]
  total: number
}

export interface ScheduleConflict {
  subject_id: number
  subject_name: string
  reason: string
}

export interface PaperInfoItem {
  subject_id: number
  subject_name?: string
  setter_teacher_id: number | null
  reviewer_teacher_id: number | null
  paper_count: number | null
}

export interface SpecialArrangement {
  id: number
  exam_id: number
  student_id: number
  student_no?: string | null
  student_name?: string | null
  arrangement_type: string
  detail: string | null
}

export interface GenerateParticipantsResult {
  created: number
  skipped: number
}

/** 状态流转顺序:草稿→已发布→进行中→成绩处理中→已发布成绩→已归档。 */
export function nextExamStatus(status: string): string | null {
  const i = EXAM_STATUSES.indexOf(status as ExamStatus)
  if (i < 0 || i >= EXAM_STATUSES.length - 1) return null
  return EXAM_STATUSES[i + 1]
}

/** 当前状态是否还能向前推进(已归档与未知状态不能推进)。 */
export function canAdvanceExamStatus(status: string): boolean {
  return nextExamStatus(status) !== null
}

/** 目标状态是否在当前状态之前(回退):回退须二次确认并写备注留痕。 */
export function isExamStatusBackward(current: string, target: string): boolean {
  const c = EXAM_STATUSES.indexOf(current as ExamStatus)
  const t = EXAM_STATUSES.indexOf(target as ExamStatus)
  return c >= 0 && t >= 0 && t < c
}

/** 草稿可改:只有草稿能改基本信息与日程,其他状态只读。 */
export function isExamDraft(status: string): boolean {
  return status === '草稿'
}

// ── 考试列表/新建/详情/复制(KW-08、KW-12) ──
export interface ListExamsParams {
  semesterId?: number | null
  status?: string | null
  q?: string
}

export function listExams(params: ListExamsParams = {}): Promise<ExamList> {
  const qs = new URLSearchParams()
  if (params.semesterId != null) qs.set('semester_id', String(params.semesterId))
  if (params.status) qs.set('status', params.status)
  if (params.q) qs.set('q', params.q)
  const suffix = qs.toString()
  return apiGet<ExamList>(`/exam/exams${suffix ? `?${suffix}` : ''}`)
}

export const getExam = (id: number) => apiGet<ExamDetail>(`/exam/exams/${id}`)

export function createExam(body: {
  semester_id: number
  name: string
  exam_type: string
  grades: number[]
  description?: string | null
}): Promise<Exam> {
  return apiPost<Exam>('/exam/exams', body)
}

export function updateExam(
  id: number,
  body: { name?: string; exam_type?: string; grades?: number[]; description?: string | null },
): Promise<Exam> {
  return request<Exam>('PATCH', `/exam/exams/${id}`, body)
}

/** 状态流转(KW-11):前进与回退都走同一端点,回退须带备注留痕。 */
export function changeExamStatus(id: number, toStatus: string, note?: string | null): Promise<Exam> {
  return apiPost<Exam>(`/exam/exams/${id}/status`, { to_status: toStatus, note: note ?? null })
}

export function copyExam(
  id: number,
  body: { name: string; semester_id: number },
): Promise<Exam> {
  return apiPost<Exam>(`/exam/exams/${id}/copy`, body)
}

// ── 考试日程(KW-09) ──
export const listExamSubjects = (id: number) =>
  apiGet<{ items: ExamSubject[] }>(`/exam/exams/${id}/subjects`)

export function saveExamSubjects(
  id: number,
  subjects: {
    subject_id: number
    exam_date: string | null
    start_time: string | null
    end_time: string | null
    full_score?: number | null
  }[],
): Promise<{ items: ExamSubject[] }> {
  return request<{ items: ExamSubject[] }>('PUT', `/exam/exams/${id}/subjects`, { subjects })
}

/** 冲突检查只提示、不阻断:KW-09 备注定“不阻断教务强制发布”。 */
export function checkExamSchedule(id: number): Promise<{ conflicts: ScheduleConflict[] }> {
  return apiPost<{ conflicts: ScheduleConflict[] }>(`/exam/exams/${id}/schedule-check`, {})
}

// ── 参试名单(KW-10) ──
export interface ListParticipantsParams {
  classUnitId?: number | null
  status?: string | null
  q?: string
}

export function listParticipants(id: number, params: ListParticipantsParams = {}): Promise<ParticipantList> {
  const qs = new URLSearchParams()
  if (params.classUnitId != null) qs.set('class_unit_id', String(params.classUnitId))
  if (params.status) qs.set('status', params.status)
  if (params.q) qs.set('q', params.q)
  const suffix = qs.toString()
  return apiGet<ParticipantList>(`/exam/exams/${id}/participants${suffix ? `?${suffix}` : ''}`)
}

export function generateParticipants(id: number): Promise<GenerateParticipantsResult> {
  return apiPost<GenerateParticipantsResult>(`/exam/exams/${id}/participants/generate`, {})
}

export function addParticipant(
  id: number,
  body: { student_id: number; note?: string | null },
): Promise<ExamParticipant> {
  return apiPost<ExamParticipant>(`/exam/exams/${id}/participants`, body)
}

export function updateParticipant(
  id: number,
  pid: number,
  body: { status?: string; note?: string | null },
): Promise<ExamParticipant> {
  return request<ExamParticipant>('PATCH', `/exam/exams/${id}/participants/${pid}`, body)
}

export function deleteParticipant(id: number, pid: number): Promise<void> {
  return request<void>('DELETE', `/exam/exams/${id}/participants/${pid}`)
}

// ── 命题与试卷信息(KW-13):只登记分工信息,不做题库组卷 ──
export const getPaperInfo = (id: number) =>
  apiGet<{ items: PaperInfoItem[] }>(`/exam/exams/${id}/paper-info`)

export function savePaperInfo(id: number, items: PaperInfoItem[]): Promise<{ items: PaperInfoItem[] }> {
  return request<{ items: PaperInfoItem[] }>('PUT', `/exam/exams/${id}/paper-info`, {
    items: items.map((it) => ({
      subject_id: it.subject_id,
      setter_teacher_id: it.setter_teacher_id ?? null,
      reviewer_teacher_id: it.reviewer_teacher_id ?? null,
      paper_count: it.paper_count ?? null,
    })),
  })
}

// ── 特殊考生安排(KW-14) ──
export const listSpecialArrangements = (id: number) =>
  apiGet<{ items: SpecialArrangement[] }>(`/exam/exams/${id}/special-arrangements`)

export function createSpecialArrangement(
  id: number,
  body: { student_id: number; arrangement_type: string; detail?: string | null },
): Promise<SpecialArrangement> {
  return apiPost<SpecialArrangement>(`/exam/exams/${id}/special-arrangements`, body)
}

export function updateSpecialArrangement(
  id: number,
  sid: number,
  body: { arrangement_type?: string; detail?: string | null },
): Promise<SpecialArrangement> {
  return request<SpecialArrangement>('PATCH', `/exam/exams/${id}/special-arrangements/${sid}`, body)
}

export function deleteSpecialArrangement(id: number, sid: number): Promise<void> {
  return request<void>('DELETE', `/exam/exams/${id}/special-arrangements/${sid}`)
}

// ── 考场编排(KW-15~22) ──
// 清单 KW-16 原文:编排前选定规则:按班级整班入考场、按成绩 S 型混排、
// 随机混排,三选一,全年级统一执行。第 3 批 brief 写错的旧选项
// student_no / class_mixed 已删掉,改成清单原文。
export const ARRANGEMENT_MODES = ['whole_class', 's_shape', 'random'] as const
export type ArrangementMode = (typeof ARRANGEMENT_MODES)[number]

export const ARRANGEMENT_MODE_LABELS: Record<ArrangementMode, string> = {
  whole_class: '按班级整班入考场',
  s_shape: '按成绩S型混排',
  random: '随机混排',
}

export interface ExamRoom {
  id: number
  exam_id: number
  room_id: number
  room_name: string
  capacity: number | null
  room_type: string | null
  is_special: boolean
}

export interface ExamRoomList {
  items: ExamRoom[]
  total: number
}

export interface ArrangementRule {
  exam_id: number
  mode: string
  scatter_same_class: boolean
  max_per_room: number | null
}

export interface ArrangeResult {
  assigned: number
  rooms_used: number
  warnings: string[]
}

export interface ArrangementItem {
  id: number
  exam_id: number
  subject_id: number | null
  subject_name: string | null
  room_id: number
  room_name: string
  student_id: number
  student_no: string
  student_name: string
  class_name: string | null
  seat_no: number | null
  special_note: string | null
  /** 考号:后端补遗在加,没加上时可能为空,前端按空处理,不崩。 */
  exam_no?: string | null
}

export interface ArrangementList {
  items: ArrangementItem[]
  total: number
}

export interface SeatMapSeat {
  seat_no: number | null
  student_no: string
  student_name: string
  class_name: string | null
  special_note: string | null
  /** 考号:后端补遗在加,没加上时可能为空,前端按空处理,不崩。 */
  exam_no?: string | null
}

export interface SeatMapRoom {
  room_id: number
  room_name: string
  seats: SeatMapSeat[]
}

export interface SeatMap {
  rooms: SeatMapRoom[]
}

export interface ArrangementLock {
  locked: boolean
  locked_by?: string | null
  locked_at?: string | null
}

/** 锁定态提示:后端 409 与锁定态按钮置灰共用同一文案,不得改写。 */
export const ARRANGEMENT_LOCKED_HINT = '已锁定，请先解锁'

/** 锁定后自动编排与手动调整都被后端拒绝,前端把相关按钮置灰。 */
export function canEditArrangement(locked: boolean): boolean {
  return !locked
}

// ── 考场设置(KW-15) ──
export const listExamRooms = (id: number) =>
  apiGet<ExamRoomList>(`/exam/exams/${id}/rooms`)

export function addExamRoom(
  id: number,
  body: { room_id: number; capacity?: number | null; room_type?: string | null; is_special?: boolean },
): Promise<ExamRoom> {
  return apiPost<ExamRoom>(`/exam/exams/${id}/rooms`, body)
}

export function deleteExamRoom(id: number, rid: number): Promise<void> {
  return request<void>('DELETE', `/exam/exams/${id}/rooms/${rid}`)
}

// ── 编排规则(KW-16) ──
export const getArrangementRule = (id: number) =>
  apiGet<ArrangementRule>(`/exam/exams/${id}/arrangement-rule`)

export function saveArrangementRule(
  id: number,
  body: { mode: string; scatter_same_class: boolean; max_per_room?: number | null },
): Promise<ArrangementRule> {
  return request<ArrangementRule>('PUT', `/exam/exams/${id}/arrangement-rule`, body)
}

// ── 自动编排(KW-17) ──
export function arrangeExam(id: number, subjectId?: number | null): Promise<ArrangeResult> {
  return apiPost<ArrangeResult>(`/exam/exams/${id}/arrange`, {
    ...(subjectId != null ? { subject_id: subjectId } : {}),
  })
}

// ── 编排结果与手工调整(KW-18) ──
export interface ListArrangementsParams {
  subjectId?: number | null
  roomId?: number | null
}

export function listArrangements(id: number, params: ListArrangementsParams = {}): Promise<ArrangementList> {
  const qs = new URLSearchParams()
  if (params.subjectId != null) qs.set('subject_id', String(params.subjectId))
  if (params.roomId != null) qs.set('room_id', String(params.roomId))
  const suffix = qs.toString()
  return apiGet<ArrangementList>(`/exam/exams/${id}/arrangements${suffix ? `?${suffix}` : ''}`)
}

export function moveArrangement(
  id: number,
  body: { assignment_id: number; to_room_id: number; seat_no?: number | null },
): Promise<ArrangementItem> {
  return apiPost<ArrangementItem>(`/exam/exams/${id}/arrangements/move`, body)
}

export function swapArrangements(
  id: number,
  body: { assignment_id_a: number; assignment_id_b: number },
): Promise<{ items: ArrangementItem[] }> {
  return apiPost<{ items: ArrangementItem[] }>(`/exam/exams/${id}/arrangements/swap`, body)
}

// ── 座位表(KW-20) ──
export function getSeatMap(id: number, subjectId?: number | null): Promise<SeatMap> {
  const qs = subjectId != null ? `?subject_id=${subjectId}` : ''
  return apiGet<SeatMap>(`/exam/exams/${id}/seat-map${qs}`)
}

// ── 考场编排表导出(KW-22):直接下载 Excel,前端不解析 ──
export function exportArrangements(id: number, subjectId?: number | null): Promise<void> {
  const qs = subjectId != null ? `?subject_id=${subjectId}` : ''
  return downloadBlob(`/exam/exams/${id}/arrangements/export${qs}`, 'arrangements.xlsx')
}

// ── 编排锁定/解锁 ──
export function lockArrangement(id: number, note?: string | null): Promise<ArrangementLock> {
  return apiPost<ArrangementLock>(`/exam/exams/${id}/arrangement-lock`, { note: note ?? null })
}

export function unlockArrangement(id: number, note?: string | null): Promise<ArrangementLock> {
  return apiPost<ArrangementLock>(`/exam/exams/${id}/arrangement-unlock`, { note: note ?? null })
}

export const getArrangementLock = (id: number) =>
  apiGet<ArrangementLock>(`/exam/exams/${id}/arrangement-lock`)

// ── 准考证打印(KW-19):批量打印,一名学生一张证,不带照片 ──
export interface AdmissionTicketSubject {
  subject_id: number
  subject_name: string
  exam_date: string | null
  start_time: string | null
  end_time: string | null
  room_name: string | null
  seat_no: number | null
}

export interface AdmissionTicket {
  student_id: number
  student_no: string
  exam_no: string | null
  student_name: string
  class_name: string | null
  subjects: AdmissionTicketSubject[]
}

export interface AdmissionTicketList {
  items: AdmissionTicket[]
  total: number
}

export interface ListAdmissionTicketsParams {
  classUnitId?: number | null
  roomId?: number | null
}

export function listAdmissionTickets(
  id: number,
  params: ListAdmissionTicketsParams = {},
): Promise<AdmissionTicketList> {
  const qs = new URLSearchParams()
  if (params.classUnitId != null) qs.set('class_unit_id', String(params.classUnitId))
  if (params.roomId != null) qs.set('room_id', String(params.roomId))
  const suffix = qs.toString()
  return apiGet<AdmissionTicketList>(`/exam/exams/${id}/admission-tickets${suffix ? `?${suffix}` : ''}`)
}

/** 准考证页班级筛选:契约的准考证记录只有 class_name、没有 class_unit_id,按班级名筛选。 */
export function ticketClassNames(items: AdmissionTicket[]): string[] {
  const names = new Set<string>()
  for (const t of items) if (t.class_name) names.add(t.class_name)
  return [...names].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))
}

export function filterTicketsByClass(
  items: AdmissionTicket[],
  className: string | null,
): AdmissionTicket[] {
  if (!className) return items
  return items.filter((t) => t.class_name === className)
}

/** 准考证各科日程按考试日期、开始时间排序。 */
export function sortTicketSubjects(subjects: AdmissionTicketSubject[]): AdmissionTicketSubject[] {
  return [...subjects].sort((a, b) => {
    const da = a.exam_date ?? ''
    const db = b.exam_date ?? ''
    if (da !== db) return da < db ? -1 : 1
    const ta = a.start_time ?? ''
    const tb = b.start_time ?? ''
    return ta < tb ? -1 : ta > tb ? 1 : 0
  })
}

// ── 考场名单与签到表(KW-20):按考场 + 科目分组 ──
export interface AttendanceGroup {
  room_id: number
  room_name: string
  subject_id: number | null
  subject_name: string | null
  items: ArrangementItem[]
}

/** 按考场 + 科目分组,组内按座位号、考号排序,供签到表逐表打印。 */
export function groupAttendanceByRoomSubject(items: ArrangementItem[]): AttendanceGroup[] {
  const map = new Map<string, AttendanceGroup>()
  for (const it of items) {
    const key = `${it.room_id}|${it.subject_id ?? ''}`
    let g = map.get(key)
    if (!g) {
      g = {
        room_id: it.room_id, room_name: it.room_name,
        subject_id: it.subject_id, subject_name: it.subject_name, items: [],
      }
      map.set(key, g)
    }
    g.items.push(it)
  }
  const groups = [...map.values()]
  for (const g of groups) {
    g.items.sort((a, b) => {
      const sa = a.seat_no ?? Number.MAX_SAFE_INTEGER
      const sb = b.seat_no ?? Number.MAX_SAFE_INTEGER
      if (sa !== sb) return sa - sb
      return compareExamNo(a.exam_no ?? '', b.exam_no ?? '')
    })
  }
  groups.sort((a, b) => {
    if (a.room_name !== b.room_name) return a.room_name.localeCompare(b.room_name, 'zh-CN')
    return (a.subject_name ?? '').localeCompare(b.subject_name ?? '', 'zh-CN')
  })
  return groups
}

// ── 考场门贴与桌贴(KW-21) ──
/** 考号比较:全是数字时按数值比,否则按字符串比。 */
export function compareExamNo(a: string, b: string): number {
  const na = Number(a)
  const nb = Number(b)
  if (a.trim() !== '' && b.trim() !== '' && Number.isFinite(na) && Number.isFinite(nb)) {
    return na - nb
  }
  return a < b ? -1 : a > b ? 1 : 0
}

/** 门贴考生起止号:取一组考号的最小与最大;没有有效考号时返回 null。 */
export function examNoRange(
  examNos: (string | null | undefined)[],
): { start: string; end: string } | null {
  const valid = examNos.filter((n): n is string => !!n && n.trim() !== '')
  if (valid.length === 0) return null
  const sorted = [...valid].sort(compareExamNo)
  return { start: sorted[0], end: sorted[sorted.length - 1] }
}

// ── 监考安排(KW-23~29) ──
// 契约见任务书(与后端 backend/app/api/exam_invigilation.py、
// backend/app/schemas/exam_invigilation.py 共用):
// 回避默认班主任避监本班、任课教师避监本学科均开,每考场监考人数默认 2;
// role 统一为“监考”,不区分主监/副监;工作量只出场次与分钟数,不折算补贴。
// 违纪类型以后端模型 DISCIPLINE_TYPES 为准:违纪、作弊、其他。
export const INVIGILATION_ROLE = '监考'
export const DISCIPLINE_TYPES = ['违纪', '作弊', '其他'] as const
export type DisciplineType = (typeof DISCIPLINE_TYPES)[number]

/** 回避规则默认值(与后端 DEFAULT_* 一致):两项回避都开,每考场 2 人。 */
export const DEFAULT_INVIGILATION_RULE = {
  avoid_own_class: true,
  avoid_own_subject: true,
  invigilators_per_room: 2,
}

export interface InvigilationRule {
  exam_id: number
  avoid_own_class: boolean
  avoid_own_subject: boolean
  invigilators_per_room: number
}

export interface InvigilatorPoolItem {
  teacher_id: number
  teacher_name: string
  eligible: boolean
}

export interface InvigilatorPool {
  items: InvigilatorPoolItem[]
  total: number
}

export interface InvigilateResult {
  assigned: number
  warnings: string[]
}

export interface Invigilation {
  id: number
  exam_id: number
  subject_id: number
  subject_name: string
  room_id: number
  room_name: string
  teacher_id: number
  teacher_name: string
  role: string
}

export interface InvigilationList {
  items: Invigilation[]
  total: number
}

export interface Patrol {
  id: number
  exam_id: number
  exam_date: string
  teacher_id: number
  teacher_name: string
  scope: string
  note: string | null
}

export interface PatrolList {
  items: Patrol[]
  total: number
}

export interface SheetSession {
  subject_name: string
  exam_date: string
  start_time: string
  end_time: string
  room_name: string
}

export interface TeacherSheetTeacher {
  teacher_id: number
  teacher_name: string
  sessions: SheetSession[]
}

export interface TeacherSheet {
  teachers: TeacherSheetTeacher[]
}

export interface RoomSheetSession {
  subject_name: string
  exam_date: string
  start_time: string
  end_time: string
  teachers: string[]
}

export interface RoomSheetRoom {
  room_id: number
  room_name: string
  sessions: RoomSheetSession[]
}

export interface RoomSheet {
  rooms: RoomSheetRoom[]
}

export type InvigilationSheetView = 'teacher' | 'room'

export const SHEET_VIEW_LABELS: Record<InvigilationSheetView, string> = {
  teacher: '按教师视图',
  room: '按考场视图',
}

/** 监考表视图归一化:只有 'room' 是考场视图,其余一律回到教师视图。 */
export function normalizeSheetView(view: string | null | undefined): InvigilationSheetView {
  return view === 'room' ? 'room' : 'teacher'
}

/** 两视图切换:教师视图与考场视图来回切。 */
export function toggleSheetView(view: InvigilationSheetView): InvigilationSheetView {
  return view === 'teacher' ? 'room' : 'teacher'
}

export interface WorkloadItem {
  teacher_id: number
  teacher_name: string
  sessions: number
  minutes: number
}

export interface Workload {
  items: WorkloadItem[]
  total: number
}

export interface Discipline {
  id: number
  exam_id: number
  subject_id: number
  subject_name: string
  student_id: number
  student_no: string
  student_name: string
  class_name: string
  type: string
  description: string | null
  handling: string | null
  recorded_by: number | null
  recorded_by_name: string
  created_at: string
}

export interface DisciplineList {
  items: Discipline[]
  total: number
}

// ── 监考规则与教师池(KW-23) ──
export const getInvigilationRule = (id: number) =>
  apiGet<InvigilationRule>(`/exam/exams/${id}/invigilation-rule`)

export function saveInvigilationRule(
  id: number,
  body: { avoid_own_class: boolean; avoid_own_subject: boolean; invigilators_per_room: number },
): Promise<InvigilationRule> {
  return request<InvigilationRule>('PUT', `/exam/exams/${id}/invigilation-rule`, body)
}

export const listInvigilators = (id: number) =>
  apiGet<InvigilatorPool>(`/exam/exams/${id}/invigilators`)

export function saveInvigilators(
  id: number,
  items: { teacher_id: number; eligible: boolean }[],
): Promise<InvigilatorPool> {
  return request<InvigilatorPool>('PUT', `/exam/exams/${id}/invigilators`, { items })
}

// ── 自动排监考(KW-24):可选科目,不选则排全部科目;warnings 原样返回 ──
export function invigilateExam(id: number, subjectId?: number | null): Promise<InvigilateResult> {
  return apiPost<InvigilateResult>(`/exam/exams/${id}/invigilate`, {
    ...(subjectId != null ? { subject_id: subjectId } : {}),
  })
}

// ── 监考安排查询与手工调整(KW-25) ──
export interface ListInvigilationsParams {
  subjectId?: number | null
  roomId?: number | null
  teacherId?: number | null
}

export function listInvigilations(
  id: number,
  params: ListInvigilationsParams = {},
): Promise<InvigilationList> {
  const qs = new URLSearchParams()
  if (params.subjectId != null) qs.set('subject_id', String(params.subjectId))
  if (params.roomId != null) qs.set('room_id', String(params.roomId))
  if (params.teacherId != null) qs.set('teacher_id', String(params.teacherId))
  const suffix = qs.toString()
  return apiGet<InvigilationList>(`/exam/exams/${id}/invigilations${suffix ? `?${suffix}` : ''}`)
}

export function createInvigilation(
  id: number,
  body: { subject_id: number; room_id: number; teacher_id: number; role?: string },
): Promise<Invigilation> {
  return apiPost<Invigilation>(`/exam/exams/${id}/invigilations`, body)
}

/** 替补换人:只改教师(与 role),其余字段不动。 */
export function updateInvigilation(
  id: number,
  iid: number,
  body: { teacher_id?: number; role?: string },
): Promise<Invigilation> {
  return request<Invigilation>('PATCH', `/exam/exams/${id}/invigilations/${iid}`, body)
}

export function deleteInvigilation(id: number, iid: number): Promise<void> {
  return request<void>('DELETE', `/exam/exams/${id}/invigilations/${iid}`)
}

// ── 巡考安排(KW-26) ──
export const listPatrols = (id: number) =>
  apiGet<PatrolList>(`/exam/exams/${id}/patrols`)

export function createPatrol(
  id: number,
  body: { exam_date: string; teacher_id: number; scope: string; note?: string | null },
): Promise<Patrol> {
  return apiPost<Patrol>(`/exam/exams/${id}/patrols`, body)
}

export function updatePatrol(
  id: number,
  pid: number,
  body: { exam_date?: string; teacher_id?: number; scope?: string; note?: string | null },
): Promise<Patrol> {
  return request<Patrol>('PATCH', `/exam/exams/${id}/patrols/${pid}`, body)
}

export function deletePatrol(id: number, pid: number): Promise<void> {
  return request<void>('DELETE', `/exam/exams/${id}/patrols/${pid}`)
}

// ── 监考表两视图(KW-27) ──
export function getTeacherSheet(id: number, subjectId?: number | null): Promise<TeacherSheet> {
  const qs = new URLSearchParams({ view: 'teacher' })
  if (subjectId != null) qs.set('subject_id', String(subjectId))
  return apiGet<TeacherSheet>(`/exam/exams/${id}/invigilation-sheets?${qs.toString()}`)
}

export function getRoomSheet(id: number, subjectId?: number | null): Promise<RoomSheet> {
  const qs = new URLSearchParams({ view: 'room' })
  if (subjectId != null) qs.set('subject_id', String(subjectId))
  return apiGet<RoomSheet>(`/exam/exams/${id}/invigilation-sheets?${qs.toString()}`)
}

/** 按当前视图取监考表:teacher 取教师视图,room 取考场视图。 */
export function getInvigilationSheet(
  id: number,
  view: InvigilationSheetView,
  subjectId?: number | null,
): Promise<TeacherSheet | RoomSheet> {
  return view === 'room' ? getRoomSheet(id, subjectId) : getTeacherSheet(id, subjectId)
}

// ── 监考工作量统计与导出(KW-28):只出场次与分钟数,不折算补贴 ──
export const getInvigilationWorkload = (id: number) =>
  apiGet<Workload>(`/exam/exams/${id}/invigilation-workload`)

export function exportInvigilationWorkload(id: number): Promise<void> {
  return downloadBlob(`/exam/exams/${id}/invigilation-workload/export`, 'invigilation_workload.xlsx')
}

// ── 考风考纪记录(KW-29) ──
export const listDiscipline = (id: number) =>
  apiGet<DisciplineList>(`/exam/exams/${id}/discipline`)

export function createDiscipline(
  id: number,
  body: { subject_id: number; student_id: number; type: string; description?: string | null; handling?: string | null },
): Promise<Discipline> {
  return apiPost<Discipline>(`/exam/exams/${id}/discipline`, body)
}

export function updateDiscipline(
  id: number,
  did: number,
  body: { subject_id?: number; student_id?: number; type?: string; description?: string | null; handling?: string | null },
): Promise<Discipline> {
  return request<Discipline>('PATCH', `/exam/exams/${id}/discipline/${did}`, body)
}

export function deleteDiscipline(id: number, did: number): Promise<void> {
  return request<void>('DELETE', `/exam/exams/${id}/discipline/${did}`)
}

// ── 阅卷与成绩录入(KW-30~35) ──
// 契约见任务书(与后端 backend/app/api/exam_scores.py、
// backend/app/schemas/exam_scores.py 共用):
// 录入模式 total_only 只录总分(默认)/itemized 录大题小分;补考口径 separate
// 单独标注(默认)/override/max;作弊计分 zero 记 0 分(默认)/null 记空;
// 缺考默认不计入统计(absent_counts 默认 false)。
// 注意后端口径(写进汇报,不改后端):补考成绩状态只能是正常/缺考/免考,
// 没有作弊;makeup_mode 为 override/max 时后端只存配置,暂不改变正考分。
export const SCORE_STATUSES = ['正常', '缺考', '作弊', '免考'] as const
export type ScoreStatus = (typeof SCORE_STATUSES)[number]
export const MAKEUP_SCORE_STATUSES = ['正常', '缺考', '免考'] as const
export type MakeupScoreStatus = (typeof MAKEUP_SCORE_STATUSES)[number]
export const ENTRY_MODES = ['total_only', 'itemized'] as const
export type EntryMode = (typeof ENTRY_MODES)[number]
export const ENTRY_MODE_LABELS: Record<EntryMode, string> = {
  total_only: '只录总分',
  itemized: '录大题小分',
}
export const MAKEUP_MODES = ['separate', 'override', 'max'] as const
export type MakeupMode = (typeof MAKEUP_MODES)[number]
export const MAKEUP_MODE_LABELS: Record<MakeupMode, string> = {
  separate: '单独标注',
  override: '覆盖正考成绩',
  max: '取正考与补考较高分',
}
export const CHEATING_SCORE_MODES = ['zero', 'null'] as const
export type CheatingScoreMode = (typeof CHEATING_SCORE_MODES)[number]
export const CHEATING_SCORE_MODE_LABELS: Record<CheatingScoreMode, string> = {
  zero: '记 0 分',
  null: '取消成绩(记空)',
}
export const MARKING_ROLES = ['阅卷组长', '阅卷教师'] as const
export type MarkingRole = (typeof MARKING_ROLES)[number]
export const MARKING_SCOPE_TYPES = ['按题', '按班'] as const
export type MarkingScopeType = (typeof MARKING_SCOPE_TYPES)[number]
export const SCORE_PROGRESS_STATUSES = ['未开始', '录入中', '已提交'] as const

/** 成绩设置默认值(与后端 ScoreSettingsPut/模型默认值一致)。 */
export const DEFAULT_SCORE_SETTINGS = {
  entry_mode: 'total_only' as EntryMode,
  makeup_mode: 'separate' as MakeupMode,
  cheating_score_mode: 'zero' as CheatingScoreMode,
  absent_counts: false,
  score_deadline: null as string | null,
}

export interface ScoreSettings {
  exam_id: number
  entry_mode: string
  makeup_mode: string
  cheating_score_mode: string
  absent_counts: boolean
  score_deadline: string | null
}

export interface MarkingAssignment {
  id: number
  exam_id: number
  subject_id: number
  subject_name: string
  teacher_id: number
  teacher_name: string
  role: string
  scope_type: string
  scope_value: string | null
}

export interface MarkingAssignmentList {
  items: MarkingAssignment[]
  total: number
}

export interface ScoreItem {
  id: number
  exam_id: number
  subject_id: number
  name: string
  max_score: number
  sort_order: number
}

export interface ScoreItemList {
  items: ScoreItem[]
  total: number
}

export interface ScoreItemValue {
  item_id: number
  name: string
  value: number
}

export interface ScoreEntryInput {
  student_id: number
  score?: number | null
  status?: string | null
  items?: { item_id: number; value: number }[]
}

export interface ScoreRecord {
  id: number | null
  exam_id: number
  subject_id: number
  student_id: number
  student_no: string
  student_name: string
  class_name: string
  score: number | null
  status: string
  submitted: boolean
  items: ScoreItemValue[]
}

export interface ScoreList {
  items: ScoreRecord[]
  total: number
}

export interface ScoreImportError {
  row: number
  message: string
}

export interface ScoreImportResult {
  created: number
  updated: number
  errors: ScoreImportError[]
}

export interface ScoreProgressClass {
  class_unit_id: number
  class_name: string
  total: number
  entered: number
  submitted: number
  status: string
}

export interface ScoreProgressSubject {
  subject_id: number
  subject_name: string
  classes: ScoreProgressClass[]
}

export interface ScoreProgress {
  subjects: ScoreProgressSubject[]
}

export interface Makeup {
  id: number
  exam_id: number
  name: string
  exam_date: string
  note: string | null
}

export interface MakeupList {
  items: Makeup[]
  total: number
}

export interface MakeupScore {
  id: number | null
  makeup_id: number
  student_id: number
  student_no: string
  student_name: string
  class_name: string
  subject_id: number
  score: number | null
  status: string
}

export interface MakeupScoreList {
  items: MakeupScore[]
  total: number
}

/** 总分校验:空值表示未录,不报错;非数字、小于 0 或超满分即时报错。 */
export function validateScore(
  value: number | null | undefined,
  fullScore: number,
): string | null {
  if (value === null || value === undefined) return null
  if (typeof value !== 'number' || Number.isNaN(value)) return '分数须为数字'
  if (value < 0 || value > fullScore) return `分数须在 0 到满分 ${fullScore} 之间`
  return null
}

/** 大题小分校验:空值不报错,超该题满分即时报错。 */
export function validateItemValue(
  value: number | null | undefined,
  item: ScoreItem,
): string | null {
  if (value === null || value === undefined) return null
  if (typeof value !== 'number' || Number.isNaN(value)) return '小分须为数字'
  if (value < 0 || value > item.max_score) {
    return `大题「${item.name}」小分须在 0 到 ${item.max_score} 之间`
  }
  return null
}

/** 小分之和(空值按 0 计),itemized 模式下总分即此和。 */
export function itemizedTotal(values: (number | null | undefined)[]): number {
  return values.reduce<number>((sum, v) => sum + (v ?? 0), 0)
}

/** itemized 总分与小分之和不一致时报错(后端同规则,422)。 */
export function validateItemizedTotal(
  total: number | null | undefined,
  values: (number | null | undefined)[],
): string | null {
  if (total === null || total === undefined) return null
  const sum = itemizedTotal(values)
  if (Math.abs(total - sum) > 1e-6) return `总分须等于小分之和(${sum}),当前总分 ${total}`
  return null
}

/** 导入逐行错误展示:后端 message 已带“第 N 行:”前缀的不再重复加。 */
export function formatImportError(err: ScoreImportError): string {
  if (/^第\s*\d+\s*行/.test(err.message)) return err.message
  return `第 ${err.row} 行: ${err.message}`
}

export function formatImportErrors(errors: ScoreImportError[]): string[] {
  return errors.map(formatImportError)
}

// ── 成绩设置(KW-30) ──
export const getScoreSettings = (id: number) =>
  apiGet<ScoreSettings>(`/exam/exams/${id}/score-settings`)

export function saveScoreSettings(
  id: number,
  body: {
    entry_mode: string
    makeup_mode: string
    cheating_score_mode: string
    absent_counts: boolean
    score_deadline?: string | null
  },
): Promise<ScoreSettings> {
  return request<ScoreSettings>('PUT', `/exam/exams/${id}/score-settings`, {
    ...body,
    score_deadline: body.score_deadline ?? null,
  })
}

// ── 阅卷分工(KW-30) ──
export function listMarkingAssignments(
  id: number,
  subjectId?: number | null,
): Promise<MarkingAssignmentList> {
  const qs = subjectId != null ? `?subject_id=${subjectId}` : ''
  return apiGet<MarkingAssignmentList>(`/exam/exams/${id}/marking-assignments${qs}`)
}

export function createMarkingAssignment(
  id: number,
  body: {
    subject_id: number
    teacher_id: number
    role?: string
    scope_type?: string
    scope_value?: string | null
  },
): Promise<MarkingAssignment> {
  return apiPost<MarkingAssignment>(`/exam/exams/${id}/marking-assignments`, body)
}

export function deleteMarkingAssignment(id: number, mid: number): Promise<void> {
  return apiDelete<void>(`/exam/exams/${id}/marking-assignments/${mid}`)
}

// ── 大题小分(KW-31):只在 itemized 模式下用 ──
export const listScoreItems = (id: number, subjectId: number) =>
  apiGet<ScoreItemList>(`/exam/exams/${id}/score-items?subject_id=${subjectId}`)

export function createScoreItem(
  id: number,
  body: { subject_id: number; name: string; max_score: number },
): Promise<ScoreItem> {
  return apiPost<ScoreItem>(`/exam/exams/${id}/score-items`, body)
}

export function deleteScoreItem(id: number, iid: number): Promise<void> {
  return apiDelete<void>(`/exam/exams/${id}/score-items/${iid}`)
}

// ── 成绩录入/提交(KW-31、KW-33) ──
export interface ListScoresParams {
  subjectId: number
  classUnitId?: number | null
  status?: string | null
  q?: string
}

export function listScores(id: number, params: ListScoresParams): Promise<ScoreList> {
  const qs = new URLSearchParams({ subject_id: String(params.subjectId) })
  if (params.classUnitId != null) qs.set('class_unit_id', String(params.classUnitId))
  if (params.status) qs.set('status', params.status)
  if (params.q) qs.set('q', params.q)
  return apiGet<ScoreList>(`/exam/exams/${id}/scores?${qs.toString()}`)
}

export function saveScores(
  id: number,
  subjectId: number,
  scores: ScoreEntryInput[],
): Promise<{ updated: number }> {
  return request<{ updated: number }>('PUT', `/exam/exams/${id}/scores`, {
    subject_id: subjectId,
    scores,
  })
}

export function submitScores(
  id: number,
  subjectId: number,
  classUnitId?: number | null,
): Promise<{ submitted: number }> {
  return apiPost<{ submitted: number }>(`/exam/exams/${id}/scores/submit`, {
    subject_id: subjectId,
    ...(classUnitId != null ? { class_unit_id: classUnitId } : {}),
  })
}

// ── 成绩批量导入(KW-32):模板下载 + 上传,逐行错误见 ScoreImportResult ──
export function downloadScoreTemplate(id: number, subjectId: number): Promise<void> {
  return downloadBlob(
    `/exam/exams/${id}/scores/template?subject_id=${subjectId}`,
    'scores_template.xlsx',
  )
}

/** 导入:有错一行都不写,后端只在全部通过时入库。 */
export async function importScores(
  id: number,
  subjectId: number,
  file: File,
): Promise<ScoreImportResult> {
  const form = new FormData()
  form.append('file', file)
  const resp = await fetch(`/api/exam/exams/${id}/scores/import?subject_id=${subjectId}`, {
    method: 'POST',
    credentials: 'include',
    body: form,
  })
  if (!resp.ok) {
    let detail = '导入失败'
    try {
      detail = (await resp.json())?.detail ?? detail
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return resp.json() as Promise<ScoreImportResult>
}

// ── 录入进度看板(KW-34) ──
export const getScoreProgress = (id: number) =>
  apiGet<ScoreProgress>(`/exam/exams/${id}/score-progress`)

// ── 补考成绩登记(KW-35) ──
export const listMakeups = (id: number) =>
  apiGet<MakeupList>(`/exam/exams/${id}/makeups`)

export function createMakeup(
  id: number,
  body: { name: string; exam_date: string; note?: string | null },
): Promise<Makeup> {
  return apiPost<Makeup>(`/exam/exams/${id}/makeups`, body)
}

export function deleteMakeup(id: number, mid: number): Promise<void> {
  return apiDelete<void>(`/exam/exams/${id}/makeups/${mid}`)
}

export const listMakeupScores = (id: number, mid: number, subjectId: number) =>
  apiGet<MakeupScoreList>(`/exam/exams/${id}/makeups/${mid}/scores?subject_id=${subjectId}`)

export function saveMakeupScores(
  id: number,
  mid: number,
  subjectId: number,
  scores: { student_id: number; score?: number | null; status?: string | null }[],
): Promise<{ updated: number }> {
  return request<{ updated: number }>('PUT', `/exam/exams/${id}/makeups/${mid}/scores`, {
    subject_id: subjectId,
    scores,
  })
}

// ── 发布与校对锁定(KW-36~40) ──
// 契约见任务书(与后端 backend/app/api/exam_publish.py、
// backend/app/schemas/exam_publish.py 共用),一个字都不能改:
// proofreader_role: subject_leader(教研组长,默认)/peer_teacher(同组教师);
// approval_levels: 1(默认)/2;publish_order: teachers_first(教师先看,默认)/sync(同步);
// objection_open 默认 true。注意后端口径(写进汇报,不改后端):
// 后端 exam_publish 路由已在 main.py 里挂载(app.include_router(exam_publish.router,
// prefix="/api/exam")),以下端点在现网可用;另:提交校对要求该范围成绩已全部提交(409),
// 锁定要求校对已通过(409),改分申请只在锁定后受理(未锁定 409),
// 异议入口关闭时登记 403,发布批次 publish_at 为空或已过期即当场已发布。
export const PROOFREADER_ROLES = ['subject_leader', 'peer_teacher'] as const
export type ProofreaderRole = (typeof PROOFREADER_ROLES)[number]
export const PROOFREADER_ROLE_LABELS: Record<ProofreaderRole, string> = {
  subject_leader: '教研组长',
  peer_teacher: '同组教师',
}
export const PUBLISH_ORDERS = ['teachers_first', 'sync'] as const
export type PublishOrder = (typeof PUBLISH_ORDERS)[number]
export const PUBLISH_ORDER_LABELS: Record<PublishOrder, string> = {
  teachers_first: '教师先看',
  sync: '同步发布',
}
export const PROOFREADING_STATUSES = ['待校对', '通过', '退回'] as const
export type ProofreadingStatus = (typeof PROOFREADING_STATUSES)[number]
export const PROOFREADING_DECISIONS = ['通过', '退回'] as const
export type ProofreadingDecision = (typeof PROOFREADING_DECISIONS)[number]
export const CHANGE_REQUEST_STATUSES = ['待审批', '已通过', '已驳回'] as const
export type ChangeRequestStatus = (typeof CHANGE_REQUEST_STATUSES)[number]
export const CHANGE_DECISIONS = ['通过', '驳回'] as const
export type ChangeDecision = (typeof CHANGE_DECISIONS)[number]
export const PUBLISH_SCOPE_TYPES = ['年级', '班级'] as const
export type PublishScopeType = (typeof PUBLISH_SCOPE_TYPES)[number]
export const PUBLISH_BATCH_STATUSES = ['待发布', '已发布', '已撤回'] as const
export type PublishBatchStatus = (typeof PUBLISH_BATCH_STATUSES)[number]
export const OBJECTION_STATUSES = ['待复核', '已回复', '已关闭'] as const
export type ObjectionStatus = (typeof OBJECTION_STATUSES)[number]

/** 发布设置默认值(与后端 DEFAULT_SETTINGS 一致)。 */
export const DEFAULT_PUBLISH_SETTINGS = {
  proofreader_role: 'subject_leader' as ProofreaderRole,
  approval_levels: 1,
  publish_order: 'teachers_first' as PublishOrder,
  objection_open: true,
}

export interface PublishSettings {
  exam_id: number
  proofreader_role: string
  approval_levels: number
  publish_order: string
  objection_open: boolean
}

export interface Proofreading {
  id: number
  exam_id: number
  subject_id: number
  subject_name: string
  class_unit_id: number | null
  class_name: string | null
  submitted_by: number | null
  submitted_by_name: string
  proofreader_id: number | null
  proofreader_name: string
  status: string
  note: string | null
}

export interface ProofreadingList {
  items: Proofreading[]
  total: number
}

export interface ScoreLock {
  id: number
  exam_id: number
  subject_id: number
  subject_name: string
  class_unit_id: number | null
  class_name: string | null
  locked_by: number | null
  locked_by_name: string
  locked_at: string | null
}

export interface ScoreLockList {
  items: ScoreLock[]
  total: number
}

export interface ChangeApproval {
  level: number
  approver_name: string
  decision: string
  note: string | null
}

export interface ScoreChangeRequest {
  id: number
  exam_id: number
  score_id: number
  student_name: string
  subject_name: string
  old_score: number | null
  new_score: number | null
  reason: string
  status: string
  requested_by: number | null
  requested_by_name: string
  approvals: ChangeApproval[]
}

export interface ScoreChangeRequestList {
  items: ScoreChangeRequest[]
  total: number
}

export interface PublishBatch {
  id: number
  exam_id: number
  scope_type: string
  scope_value: number
  publish_at: string | null
  status: string
  published_by: number | null
  published_by_name: string
  note: string | null
}

export interface PublishBatchList {
  items: PublishBatch[]
  total: number
}

export interface PublishStatusBatch {
  scope_type: string
  scope_value: number
  status: string
  publish_at: string | null
}

export interface PublishStatus {
  exam_id: number
  batches: PublishStatusBatch[]
  all_published: boolean
}

export interface Objection {
  id: number
  exam_id: number
  score_id: number
  student_id: number
  student_name: string
  subject_name: string
  content: string
  status: string
  reply: string | null
  replied_by: number | null
  replied_by_name: string
  raised_by_role: string
}

export interface ObjectionList {
  items: Objection[]
  total: number
}

/** 校对通过才能锁定(与后端 _proofreading_passed 同规则):
 * 全科通过覆盖全部班级;单班通过只覆盖本班;全科锁定只认全科通过。 */
export function canLockAfterProofreading(
  items: Proofreading[],
  subjectId: number,
  classUnitId?: number | null,
): boolean {
  const target = classUnitId ?? null
  return items.some(
    (it) =>
      it.subject_id === subjectId &&
      it.status === '通过' &&
      (it.class_unit_id == null || it.class_unit_id === target),
  )
}

/** 改分审批层级文案:一层时教研组长或教务一人决定;两层时第一层教研组长、第二层教务。 */
export function approvalLevelLabel(level: number, totalLevels: number): string {
  if (totalLevels <= 1) return '教研组长或教务'
  return level === 1 ? '第一层 · 教研组长' : '第二层 · 教务'
}

/** 改分申请下一层审批层级:已终结(通过/驳回)或层级已走完时为 null。 */
export function nextChangeApprovalLevel(
  req: ScoreChangeRequest,
  totalLevels: number,
): number | null {
  if (req.status !== '待审批') return null
  const next = req.approvals.length + 1
  return next <= totalLevels ? next : null
}

/** 改分审批进度文案:待审批时写明下一层由谁审,终结时写明共几层、已审几层。 */
export function changeApprovalProgressText(
  req: ScoreChangeRequest,
  totalLevels: number,
): string {
  if (req.status === '已通过') return `已通过(共 ${totalLevels} 层)`
  if (req.status === '已驳回') return `已驳回(已审批 ${req.approvals.length} 层)`
  const next = nextChangeApprovalLevel(req, totalLevels)
  if (next == null) return '待审批'
  return `待审批 · 下一层:${approvalLevelLabel(next, totalLevels)}`
}

/** 发布范围文案:年级直接写年级数,班级优先写班级名、未知时写班级编号。 */
export function formatPublishScope(
  scopeType: string,
  scopeValue: number,
  className?: string | null,
): string {
  if (scopeType === '年级') return `${scopeValue} 年级`
  return className ? `班级 ${className}` : `班级 ${scopeValue}`
}

/** 发布批次可撤回:只有已撤回的不能重复撤回(待发布与已发布都可撤回)。 */
export function isPublishBatchWithdrawable(batch: PublishBatch): boolean {
  return batch.status !== '已撤回'
}

/** 异议可回复:只有待复核的能回复;可关闭:只有已回复的能关闭(与后端同规则)。 */
export function isObjectionReplyable(o: Objection): boolean {
  return o.status === '待复核'
}

export function isObjectionClosable(o: Objection): boolean {
  return o.status === '已回复'
}

// ── 发布设置(KW-36~40 共用) ──
export const getPublishSettings = (id: number) =>
  apiGet<PublishSettings>(`/exam/exams/${id}/publish-settings`)

export function savePublishSettings(
  id: number,
  body: {
    proofreader_role: string
    approval_levels: number
    publish_order: string
    objection_open: boolean
  },
): Promise<PublishSettings> {
  return apiPut<PublishSettings>(`/exam/exams/${id}/publish-settings`, body)
}

// ── 双人校对确认(KW-36) ──
export interface ListProofreadingParams {
  subjectId?: number | null
  classUnitId?: number | null
}

export function listProofreading(
  id: number,
  params: ListProofreadingParams = {},
): Promise<ProofreadingList> {
  const qs = new URLSearchParams()
  if (params.subjectId != null) qs.set('subject_id', String(params.subjectId))
  if (params.classUnitId != null) qs.set('class_unit_id', String(params.classUnitId))
  const suffix = qs.toString()
  return apiGet<ProofreadingList>(`/exam/exams/${id}/proofreading${suffix ? `?${suffix}` : ''}`)
}

export function submitProofreading(
  id: number,
  body: { subject_id: number; class_unit_id?: number | null; note?: string | null },
): Promise<Proofreading> {
  return apiPost<Proofreading>(`/exam/exams/${id}/proofreading`, {
    subject_id: body.subject_id,
    ...(body.class_unit_id != null ? { class_unit_id: body.class_unit_id } : {}),
    ...(body.note ? { note: body.note } : {}),
  })
}

export function decideProofreading(
  id: number,
  pid: number,
  body: { decision: string; note?: string | null },
): Promise<Proofreading> {
  return apiPost<Proofreading>(`/exam/exams/${id}/proofreading/${pid}/decide`, {
    decision: body.decision,
    note: body.note ?? null,
  })
}

// ── 成绩提交与锁定(KW-37) ──
export const listLocks = (id: number) =>
  apiGet<ScoreLockList>(`/exam/exams/${id}/locks`)

export function createLock(
  id: number,
  body: { subject_id: number; class_unit_id?: number | null },
): Promise<ScoreLock> {
  return apiPost<ScoreLock>(`/exam/exams/${id}/locks`, {
    subject_id: body.subject_id,
    ...(body.class_unit_id != null ? { class_unit_id: body.class_unit_id } : {}),
  })
}

export function deleteLock(id: number, lid: number): Promise<void> {
  return apiDelete<void>(`/exam/exams/${id}/locks/${lid}`)
}

// ── 改分审批与留痕(KW-38) ──
export function listChangeRequests(
  id: number,
  status?: string | null,
): Promise<ScoreChangeRequestList> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : ''
  return apiGet<ScoreChangeRequestList>(`/exam/exams/${id}/score-change-requests${qs}`)
}

export function createChangeRequest(
  id: number,
  body: { score_id: number; new_score?: number | null; reason: string },
): Promise<ScoreChangeRequest> {
  return apiPost<ScoreChangeRequest>(`/exam/exams/${id}/score-change-requests`, {
    score_id: body.score_id,
    new_score: body.new_score ?? null,
    reason: body.reason,
  })
}

export function decideChangeRequest(
  id: number,
  rid: number,
  body: { decision: string; note?: string | null },
): Promise<ScoreChangeRequest> {
  return apiPost<ScoreChangeRequest>(
    `/exam/exams/${id}/score-change-requests/${rid}/decide`,
    { decision: body.decision, note: body.note ?? null },
  )
}

// ── 成绩分批发布(KW-39) ──
export const listPublishBatches = (id: number) =>
  apiGet<PublishBatchList>(`/exam/exams/${id}/publish-batches`)

export function createPublishBatch(
  id: number,
  body: {
    scope_type: string
    scope_value: number
    publish_at?: string | null
    note?: string | null
  },
): Promise<PublishBatch> {
  return apiPost<PublishBatch>(`/exam/exams/${id}/publish-batches`, {
    scope_type: body.scope_type,
    scope_value: body.scope_value,
    publish_at: body.publish_at ?? null,
    ...(body.note ? { note: body.note } : {}),
  })
}

export function withdrawPublishBatch(
  id: number,
  bid: number,
  note?: string | null,
): Promise<PublishBatch> {
  return apiPost<PublishBatch>(`/exam/exams/${id}/publish-batches/${bid}/withdraw`, {
    note: note ?? null,
  })
}

/** 执行到期发布:把已到发布时间的待发布批次翻为已发布,返回本次发布数。 */
export function publishDue(id: number): Promise<{ published: number }> {
  return apiPost<{ published: number }>(`/exam/exams/${id}/publish-due`, {})
}

export const getPublishStatus = (id: number) =>
  apiGet<PublishStatus>(`/exam/exams/${id}/publish-status`)

// ── 查分与成绩异议登记(KW-40) ──
export function listObjections(
  id: number,
  status?: string | null,
): Promise<ObjectionList> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : ''
  return apiGet<ObjectionList>(`/exam/exams/${id}/objections${qs}`)
}

export function createObjection(
  id: number,
  body: { score_id: number; content: string },
): Promise<Objection> {
  return apiPost<Objection>(`/exam/exams/${id}/objections`, body)
}

export function replyObjection(
  id: number,
  oid: number,
  body: { reply: string },
): Promise<Objection> {
  return apiPost<Objection>(`/exam/exams/${id}/objections/${oid}/reply`, body)
}

export function closeObjection(id: number, oid: number): Promise<Objection> {
  return apiPost<Objection>(`/exam/exams/${id}/objections/${oid}/close`)
}

// ── 成绩分析(KW-41~51) ──
// 契约见任务书(与后端 backend/app/api/exam_analysis.py、
// backend/app/schemas/exam_analysis.py 共用),一个字都不能改:
// 排名并列 dense 同分同名次(默认)/competition 同分并列占位;分段粒度默认 10;
// 临界浮动 critical_margin 与 subject_critical_margin 默认 5;率值与占比
// (pass_rate/excellent_rate/low_rate/pct)后端一律按 0~100 的百分比返回,
// 前端直接加 % 展示,不再乘 100。质量对比仅管理角色可见,其余后端 403,
// 前端原样展示;进退步无上次同类考试时后端返回 message,前端原样展示。
export const RANK_TIE_RULES = ['dense', 'competition'] as const
export type RankTieRule = (typeof RANK_TIE_RULES)[number]
export const RANK_TIE_RULE_LABELS: Record<RankTieRule, string> = {
  dense: '同分同名次',
  competition: '同分并列占位',
}

/** 分析设置默认值(与后端 AnalysisSettingsPut/模型默认值一致)。 */
export const DEFAULT_ANALYSIS_SETTINGS = {
  rank_tie_rule: 'dense' as RankTieRule,
  segment_size: 10,
  critical_total_line: null as number | null,
  critical_margin: 5,
  subject_critical_margin: 5,
}

/** 进退步无上次同类考试时的提示:后端原样返回,前端必须原样展示,不得改写或省略。 */
export const PROGRESS_NO_PREV_MESSAGE = '暂无上次同类考试，无法对比'

/** 质量对比无权限时的提示:以后端 403 的 detail 为准,前端原样展示。 */
export const QUALITY_COMPARE_FORBIDDEN_HINT = '质量对比仅对管理角色开放'

export interface AnalysisSettings {
  exam_id: number
  rank_tie_rule: string
  segment_size: number
  critical_total_line: number | null
  critical_margin: number
  subject_critical_margin: number
}

export interface SubjectThreshold {
  id: number
  exam_id: number
  subject_id: number
  subject_name: string
  pass_line: number | null
  excellent_line: number | null
}

export interface SubjectStats {
  subject_id: number
  subject_name: string
  count: number
  avg: number | null
  max: number | null
  min: number | null
  std: number | null
  pass_rate: number
  excellent_rate: number
  low_rate: number
}

export interface AnalysisSummary {
  scope: string
  totals: { count: number; avg: number | null; max: number | null; min: number | null; std: number | null }
  subjects: SubjectStats[]
}

export interface RankingItem {
  student_id: number
  student_no: string
  student_name: string
  class_name: string
  total: number | null
  rank: number
}

export interface RankingList {
  items: RankingItem[]
  total: number
}

export interface Segment {
  label: string
  count: number
  pct: number
}

export interface SubjectGap {
  subject_name: string
  score: number | null
  gap: number | null
}

export interface CriticalItem {
  student_id: number
  student_no: string
  student_name: string
  class_name: string
  total: number | null
  gap_to_line: number | null
  subject_gaps: SubjectGap[]
}

export interface TargetStudent {
  id: number
  exam_id: number
  student_id: number
  student_no: string
  student_name: string
  class_name: string
  target_total: number | null
  note: string | null
}

export interface TargetTrackingItem {
  student_id: number
  student_no: string
  student_name: string
  class_name: string
  target_total: number | null
  total: number | null
  reached: boolean
  weak_subjects: string[]
}

export interface ProgressItem {
  student_id: number
  student_no: string
  student_name: string
  class_name: string
  prev_total: number | null
  total: number | null
  prev_rank: number | null
  rank: number | null
  delta: number | null
}

export interface AnalysisProgress {
  items: ProgressItem[]
  top_improved: ProgressItem[]
  top_declined: ProgressItem[]
  message?: string | null
}

export interface QualityClassSubject {
  class_unit_id: number
  class_name: string
  avg: number | null
  pass_rate: number
  excellent_rate: number
}

export interface QualitySubject {
  subject_id: number
  subject_name: string
  classes: QualityClassSubject[]
}

export interface QualityClassSubjectRate {
  subject_id: number
  subject_name: string
  avg: number | null
  pass_rate: number
}

export interface QualityClass {
  class_unit_id: number
  class_name: string
  subjects: QualityClassSubjectRate[]
}

export interface QualityCompare {
  subjects: QualitySubject[]
  classes: QualityClass[]
}

export interface TrendExam {
  exam_id: number
  exam_name: string
  exam_date: string | null
  total: number | null
  subjects: Record<string, number | null>
}

export interface StudentTrend {
  student_id: number
  student_name: string
  exams: TrendExam[]
}

export interface GradeBand {
  id: number
  exam_id: number
  subject_id: number | null
  grade_label: string
  min_score: number
  max_score: number
}

export interface GradeDistributionBand {
  grade_label: string
  count: number
  pct: number
}

export type AnalysisScope = 'grade' | 'class'

export const ANALYSIS_SCOPE_LABELS: Record<AnalysisScope, string> = {
  grade: '年级',
  class: '班级',
}

/** 汇总范围归一化:只有 'class' 是班级,其余一律回到年级。 */
export function normalizeAnalysisScope(scope: string | null | undefined): AnalysisScope {
  return scope === 'class' ? 'class' : 'grade'
}

/** 并列规则说明:两种规则下同分并列后的下一名次不同,是排名展示的核心口径。 */
export function tieRuleHint(rule: string): string {
  if (rule === 'competition') return '同分并列占位:同分同名次,下一名次按并列人数跳过(如第 1 名并列 2 人,下一名次为第 3 名)'
  return '同分同名次:同分同名次,下一名次连续(如第 1 名并列 2 人,下一名次为第 2 名)'
}

/** 同分并列后的下一名次:dense 连续,competition 按并列人数跳过。 */
export function nextRankAfterTie(rule: string, rank: number, tieCount: number): number {
  if (rule === 'competition') return rank + Math.max(tieCount, 1)
  return rank + 1
}

/** 并列组:按总分分组,同分同名次的行归为一组,供排名表打“并列”标记与并列说明。 */
export function tieGroups(items: RankingItem[]): { total: number | null; rank: number; count: number }[] {
  const map = new Map<string, { total: number | null; rank: number; count: number }>()
  for (const it of items) {
    const key = `${it.rank}|${it.total ?? ''}`
    const g = map.get(key)
    if (g) g.count += 1
    else map.set(key, { total: it.total, rank: it.rank, count: 1 })
  }
  return [...map.values()].sort((a, b) => a.rank - b.rank)
}

/** 进退步提示:有上次考试时返回 null,无上次考试时原样返回后端的 message。 */
export function progressEmptyMessage(progress: AnalysisProgress): string | null {
  if (progress.items.length > 0) return null
  return progress.message ?? PROGRESS_NO_PREV_MESSAGE
}

/** 百分比展示:后端已按 0~100 返回,直接加 %,空值显示 —。 */
export function formatPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `${value}%`
}

/** 分数展示:空值显示 —,否则保留原值。 */
export function formatScore(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return String(value)
}

// ── 分析设置(KW-41~44 共用):排名并列规则、分段粒度、临界线与浮动分值 ──
export const getAnalysisSettings = (id: number) =>
  apiGet<AnalysisSettings>(`/exam/exams/${id}/analysis-settings`)

export function saveAnalysisSettings(
  id: number,
  body: {
    rank_tie_rule: string
    segment_size: number
    critical_total_line?: number | null
    critical_margin: number
    subject_critical_margin: number
  },
): Promise<AnalysisSettings> {
  return request<AnalysisSettings>('PUT', `/exam/exams/${id}/analysis-settings`, {
    rank_tie_rule: body.rank_tie_rule,
    segment_size: body.segment_size,
    critical_total_line: body.critical_total_line ?? null,
    critical_margin: body.critical_margin,
    subject_critical_margin: body.subject_critical_margin,
  })
}

// ── 科目及格优秀线覆盖(KW-43):覆盖本次考试单科的及格/优秀线 ──
export const listSubjectThresholds = (id: number) =>
  apiGet<{ items: SubjectThreshold[] }>(`/exam/exams/${id}/subject-thresholds`)

export function saveSubjectThresholds(
  id: number,
  items: { subject_id: number; pass_line?: number | null; excellent_line?: number | null }[],
): Promise<{ items: SubjectThreshold[] }> {
  return request<{ items: SubjectThreshold[] }>('PUT', `/exam/exams/${id}/subject-thresholds`, {
    items: items.map((it) => ({
      subject_id: it.subject_id,
      pass_line: it.pass_line ?? null,
      excellent_line: it.excellent_line ?? null,
    })),
  })
}

// ── 汇总(KW-41、KW-43):总分与各科均分/最高/最低/标准差/及格优秀率 ──
export interface AnalysisSummaryParams {
  scope?: AnalysisScope
  grade?: number | null
  classUnitId?: number | null
}

export function getAnalysisSummary(id: number, params: AnalysisSummaryParams = {}): Promise<AnalysisSummary> {
  const qs = new URLSearchParams({ scope: params.scope ?? 'grade' })
  if (params.grade != null) qs.set('grade', String(params.grade))
  if (params.classUnitId != null) qs.set('class_unit_id', String(params.classUnitId))
  return apiGet<AnalysisSummary>(`/exam/exams/${id}/analysis/summary?${qs.toString()}`)
}

// ── 排名(KW-42):总分与单科、年级与班级 ──
export interface AnalysisRankingsParams {
  scope?: AnalysisScope
  subjectId?: number | null
  grade?: number | null
  classUnitId?: number | null
}

export function getAnalysisRankings(id: number, params: AnalysisRankingsParams = {}): Promise<RankingList> {
  const qs = new URLSearchParams({ scope: params.scope ?? 'grade' })
  if (params.subjectId != null) qs.set('subject_id', String(params.subjectId))
  if (params.grade != null) qs.set('grade', String(params.grade))
  if (params.classUnitId != null) qs.set('class_unit_id', String(params.classUnitId))
  return apiGet<RankingList>(`/exam/exams/${id}/analysis/rankings?${qs.toString()}`)
}

// ── 分数段分布(KW-44):总分或单科,分段粒度取分析设置 ──
export interface AnalysisSegmentsParams {
  subjectId?: number | null
  scope?: AnalysisScope
  grade?: number | null
  classUnitId?: number | null
}

export function getAnalysisSegments(id: number, params: AnalysisSegmentsParams = {}): Promise<{ segments: Segment[] }> {
  const qs = new URLSearchParams({ scope: params.scope ?? 'grade' })
  if (params.subjectId != null) qs.set('subject_id', String(params.subjectId))
  if (params.grade != null) qs.set('grade', String(params.grade))
  if (params.classUnitId != null) qs.set('class_unit_id', String(params.classUnitId))
  return apiGet<{ segments: Segment[] }>(`/exam/exams/${id}/analysis/segments?${qs.toString()}`)
}

// ── 临界生(KW-45):总分临界线与单科及格线上下浮动范围内 ──
export const getAnalysisCritical = (id: number) =>
  apiGet<{ items: CriticalItem[] }>(`/exam/exams/${id}/analysis/critical`)

// ── 目标生(KW-46):名单维护 + 达标与短板跟踪 ──
export const listTargetStudents = (id: number) =>
  apiGet<{ items: TargetStudent[] }>(`/exam/exams/${id}/target-students`)

export function createTargetStudent(
  id: number,
  body: { student_id: number; target_total?: number | null; note?: string | null },
): Promise<TargetStudent> {
  return apiPost<TargetStudent>(`/exam/exams/${id}/target-students`, {
    student_id: body.student_id,
    target_total: body.target_total ?? null,
    note: body.note ?? null,
  })
}

export function deleteTargetStudent(id: number, tid: number): Promise<void> {
  return request<void>('DELETE', `/exam/exams/${id}/target-students/${tid}`)
}

export const getTargetTracking = (id: number) =>
  apiGet<{ items: TargetTrackingItem[] }>(`/exam/exams/${id}/analysis/target-tracking`)

// ── 进退步分析(KW-47):与上一次同类考试对比 ──
export const getAnalysisProgress = (id: number) =>
  apiGet<AnalysisProgress>(`/exam/exams/${id}/analysis/progress`)

// ── 学科与班级质量对比(KW-48):仅管理角色可见,其余后端 403,前端原样展示 ──
export function getQualityCompare(id: number, grade?: number | null): Promise<QualityCompare> {
  const qs = grade != null ? `?grade=${grade}` : ''
  return apiGet<QualityCompare>(`/exam/exams/${id}/analysis/quality-compare${qs}`)
}

// ── 学生个人成绩趋势(KW-49):历次考试总分与各科,表格展示 ──
export function getStudentTrend(id: number, studentId: number): Promise<StudentTrend> {
  return apiGet<StudentTrend>(`/exam/exams/${id}/analysis/trend?student_id=${studentId}`)
}

// ── 等第档与等第分布(KW-50):按分数线划分等第 ──
export function listGradeBands(id: number, subjectId?: number | null): Promise<{ items: GradeBand[] }> {
  const qs = subjectId != null ? `?subject_id=${subjectId}` : ''
  return apiGet<{ items: GradeBand[] }>(`/exam/exams/${id}/grade-bands${qs}`)
}

export function saveGradeBands(
  id: number,
  items: { subject_id?: number | null; grade_label: string; min_score: number; max_score: number }[],
): Promise<{ items: GradeBand[] }> {
  return request<{ items: GradeBand[] }>('PUT', `/exam/exams/${id}/grade-bands`, {
    items: items.map((it) => ({
      subject_id: it.subject_id ?? null,
      grade_label: it.grade_label,
      min_score: it.min_score,
      max_score: it.max_score,
    })),
  })
}

export function getGradeDistribution(
  id: number,
  subjectId?: number | null,
): Promise<{ bands: GradeDistributionBand[] }> {
  const qs = subjectId != null ? `?subject_id=${subjectId}` : ''
  return apiGet<{ bands: GradeDistributionBand[] }>(
    `/exam/exams/${id}/analysis/grade-distribution${qs}`,
  )
}

// ── 报表包导出(KW-51):多表 Excel 直接下载,前端不解析 ──
export function downloadReportPack(id: number): Promise<void> {
  return downloadBlob(`/exam/exams/${id}/analysis/report-pack`, 'report_pack.xlsx')
}

// ── 成绩单与查询(KW-52~56) ──
// 契约见任务书(与后端 backend/app/api/exam_reports.py、
// backend/app/schemas/exam_reports.py 共用),一个字都不能改:
// report-settings 默认 false/false,家长版默认不显示年级排名;
// my-scores / my-report-card 的排名键按家长版设置决定是否出现,
// 后端直接删键,不回固定 response_model,前端按“键在不在”判断显示,
// 不得自行补排名;未发布时后端 403,detail 原样展示。
// 注意后端口径(写进汇报,不改后端):my-scores 未关联任何参试学生时
// 回空 items(不报 403);初始口令只在开通当次回传,已存在账号不回传口令;
// 账号重置口令最短 8 位(后端 settings.min_password_length)。
export interface ReportSubjectScore {
  subject_id: number
  subject_name: string
  score: number | null
  status: string
}

export interface ReportCardStudent {
  student_id: number
  student_no: string
  student_name: string
  subjects: ReportSubjectScore[]
  total: number | null
  class_rank: number | null
  grade_rank: number | null
}

export interface ClassReportCard {
  class_unit_id: number
  class_name: string
  students: ReportCardStudent[]
}

export interface StudentReportCard extends ReportCardStudent {
  class_name: string
}

export interface ReportSettings {
  exam_id: number
  parent_show_grade_rank: boolean
  parent_show_class_rank: boolean
}

/** 成绩单设置默认值(与后端 ReportSettingOut 默认一致):两项都不显示。 */
export const DEFAULT_REPORT_SETTINGS = {
  parent_show_grade_rank: false,
  parent_show_class_rank: false,
}

export interface TeacherScoreItem {
  student_id: number
  student_no: string
  student_name: string
  class_name: string
  subject_id: number
  subject_name: string
  score: number | null
  status: string
  total: number | null
  class_rank: number | null
  grade_rank: number | null
}

export interface TeacherScoreList {
  items: TeacherScoreItem[]
  total: number
}

/** 学生/家长自助成绩:排名键按家长版设置决定是否出现,故设为可选。 */
export interface MyScoreItem {
  exam_id: number
  exam_name: string
  student_id: number
  student_no: string
  student_name: string
  subjects: ReportSubjectScore[]
  total: number | null
  class_rank?: number | null
  grade_rank?: number | null
}

export interface MyScores {
  items: MyScoreItem[]
}

/** 学生/家长个人成绩单:排名键同样按设置决定是否出现,故设为可选。 */
export interface MyReportCard {
  student_id: number
  student_no: string
  student_name: string
  class_name: string
  subjects: ReportSubjectScore[]
  total: number | null
  class_rank?: number | null
  grade_rank?: number | null
}

export interface AccountCredential {
  username: string
  role: string
  initial_password: string
  student_name: string
}

export interface ProvisionResult {
  students_created: number
  parents_created: number
  credentials: AccountCredential[]
}

export interface ExamAccount {
  user_id: number
  username: string
  role: string
  student_names: string[]
  must_change_password: boolean
}

export interface AccountList {
  items: ExamAccount[]
  total: number
}

export const ACCOUNT_ROLE_LABELS: Record<string, string> = {
  student: '学生',
  parent: '家长',
}

export function accountRoleLabel(role: string): string {
  return ACCOUNT_ROLE_LABELS[role] ?? role
}

/** 初始口令只显示一次的醒目提示:开通页与分发表共用同一文案,不得改写。 */
export const PROVISION_ONCE_HINT = '口令只显示一次，请立即分发，关闭后无法再次查看'

/** 未发布时后端 403 的 detail,前端原样展示,不得改写或省略“本次”。 */
export const MY_SCORES_NOT_PUBLISHED = '本次考试成绩尚未发布'

/**
 * 家长版排名是否显示:以后端回传的键在不在为准。
 * 后端按 report-settings 删键(不显示的排名键直接缺失),前端不得自行补排名;
 * 键在但值为 null(无总分未排名)时同样不显示数字。
 */
export function rankVisible(
  card: { class_rank?: number | null; grade_rank?: number | null },
  kind: 'class' | 'grade',
): boolean {
  if (kind === 'class') return 'class_rank' in card && card.class_rank != null
  return 'grade_rank' in card && card.grade_rank != null
}

/**
 * 家长版排名隐藏(与后端 _apply_parent_rank_settings 同规则,供单测与
 * 本地兜底用):设置不显示的排名键直接删掉,不留 null。
 */
export function applyParentRankVisibility<T extends { class_rank?: number | null; grade_rank?: number | null }>(
  card: T,
  settings: { parent_show_class_rank: boolean; parent_show_grade_rank: boolean },
): T {
  const out = { ...card }
  if (!settings.parent_show_class_rank) delete out.class_rank
  if (!settings.parent_show_grade_rank) delete out.grade_rank
  return out
}

/** 分发表 CSV:表头用户名、角色、学生、初始口令;学生名含逗号时加引号。 */
export function buildCredentialCsv(credentials: AccountCredential[]): string {
  const esc = (v: string) => (/[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v)
  const lines = ['用户名,角色,学生,初始口令']
  for (const c of credentials) {
    lines.push(
      [c.username, accountRoleLabel(c.role), c.student_name, c.initial_password]
        .map(esc).join(','),
    )
  }
  return lines.join('\n')
}

/** 成绩单显示设置(KW-53):家长版是否显示班级/年级排名,默认都不显示。 */
export const getReportSettings = (id: number) =>
  apiGet<ReportSettings>(`/exam/exams/${id}/report-settings`)

export function saveReportSettings(
  id: number,
  body: { parent_show_grade_rank: boolean; parent_show_class_rank: boolean },
): Promise<ReportSettings> {
  return request<ReportSettings>('PUT', `/exam/exams/${id}/report-settings`, body)
}

/** 班级成绩单(KW-52):班主任版,含总分与排名,按班级出全科成绩单。 */
export function getClassReportCard(id: number, classUnitId: number): Promise<ClassReportCard> {
  return apiGet<ClassReportCard>(
    `/exam/exams/${id}/report-cards/class?class_unit_id=${classUnitId}`,
  )
}

/** 学生个人成绩单完整版(KW-53,教师/教务用):各科成绩、总分、含排名。 */
export function getStudentReportCard(id: number, studentId: number): Promise<StudentReportCard> {
  return apiGet<StudentReportCard>(
    `/exam/exams/${id}/report-cards/student?student_id=${studentId}`,
  )
}

/** 教师端成绩查询(KW-54):按科目/班级/关键词检索,含总分与排名。 */
export interface ListTeacherScoresParams {
  subjectId?: number | null
  classUnitId?: number | null
  q?: string
}

export function listTeacherScores(
  id: number,
  params: ListTeacherScoresParams = {},
): Promise<TeacherScoreList> {
  const qs = new URLSearchParams()
  if (params.subjectId != null) qs.set('subject_id', String(params.subjectId))
  if (params.classUnitId != null) qs.set('class_unit_id', String(params.classUnitId))
  if (params.q) qs.set('q', params.q)
  const suffix = qs.toString()
  return apiGet<TeacherScoreList>(`/exam/exams/${id}/teacher-scores${suffix ? `?${suffix}` : ''}`)
}

/** 学生/家长自助查询(KW-55):查本人(孩子)的成绩;未发布后端 403。 */
export function getMyScores(examId: number): Promise<MyScores> {
  return apiGet<MyScores>(`/exam/my-scores?exam_id=${examId}`)
}

/** 学生/家长个人成绩单(KW-55):家长版按设置决定是否含排名。 */
export function getMyReportCard(examId: number, studentId: number): Promise<MyReportCard> {
  return apiGet<MyReportCard>(`/exam/my-report-card?exam_id=${examId}&student_id=${studentId}`)
}

/** 学生/家长账号一键开通(KW-55):初始口令只在本次回传中出现一次。 */
export function provisionAccounts(semesterId: number): Promise<ProvisionResult> {
  return apiPost<ProvisionResult>(`/exam/accounts/provision?semester_id=${semesterId}`, {})
}

/** 学生/家长账号清单(KW-55):按学期/角色/关键词筛选。 */
export interface ListAccountsParams {
  semesterId?: number | null
  role?: string | null
  q?: string
}

export function listAccounts(params: ListAccountsParams = {}): Promise<AccountList> {
  const qs = new URLSearchParams()
  if (params.semesterId != null) qs.set('semester_id', String(params.semesterId))
  if (params.role) qs.set('role', params.role)
  if (params.q) qs.set('q', params.q)
  const suffix = qs.toString()
  return apiGet<AccountList>(`/exam/accounts${suffix ? `?${suffix}` : ''}`)
}

/** 重置学生/家长账号口令(KW-55):新口令最短 8 位,重置后须改密。 */
export function resetAccountPassword(userId: number, newPassword: string): Promise<{ status: string }> {
  return apiPost<{ status: string }>(`/exam/accounts/${userId}/reset-password`, {
    new_password: newPassword,
  })
}

/** 成绩归档表导出(KW-56):完整成绩册 Excel 直接下载,前端不解析。 */
export function exportGradeBook(id: number): Promise<void> {
  return downloadBlob(`/exam/exams/${id}/grade-book/export`, 'grade_book.xlsx')
}

// ── 通知与提醒(KW-57~61) ──
// 契约见任务书(与后端 backend/app/api/exam_notifications.py、
// backend/app/schemas/exam_notifications.py 共用):
// 四类通知开关默认全开;手动触发四类通知与到期扫都只回 sent/failed;
// 通知类型只有考试日程/监考提醒/录分截止/成绩发布,状态只有成功/失败/待发送,
// 渠道只有钉钉/站内;只重发失败记录。触发与重发只限 admin/director,
// 越权时后端回 403,前端原样展示,不自行放行。
// 注意后端口径(写进汇报,不改后端):到期扫是全校范围(POST /notifications/remind-due
// 不带考试 id),同一提醒 24 小时内不重复发;录分截止提醒要求考试已设置
// 录分截止时间,未设置时后端回 409;成绩发布通知只在已有“已发布”批次时
// 才有接收对象;后端没有“未录完教师数”查询接口,未录完人数以后端
// 录分进度(getScoreProgress)为准,前端只做汇总展示,不另算教师数。
export const NOTIFICATION_TYPES = ['考试日程', '监考提醒', '录分截止', '成绩发布'] as const
export type NotificationType = (typeof NOTIFICATION_TYPES)[number]
export const NOTIFICATION_STATUSES = ['成功', '失败', '待发送'] as const
export type NotificationStatus = (typeof NOTIFICATION_STATUSES)[number]
export const NOTIFICATION_CHANNELS = ['钉钉', '站内'] as const

/** 通知设置默认值(与后端 NotificationSettingOut 默认值一致):四类全开。 */
export const DEFAULT_NOTIFICATION_SETTINGS = {
  schedule_notify_enabled: true,
  invigilation_remind_enabled: true,
  score_deadline_remind_enabled: true,
  publish_notify_enabled: true,
}

export interface NotificationSettings {
  exam_id: number
  schedule_notify_enabled: boolean
  invigilation_remind_enabled: boolean
  score_deadline_remind_enabled: boolean
  publish_notify_enabled: boolean
}

export interface NotifyResult {
  sent: number
  failed: number
}

export interface ExamNotification {
  id: number
  exam_id: number
  notification_type: string
  recipient_name: string
  channel: string
  status: string
  message: string
  error: string | null
  sent_at: string | null
  created_at: string | null
}

export interface NotificationList {
  items: ExamNotification[]
  total: number
}

export interface ResendResult {
  sent: boolean
  status: string
}

/** 发送结果文案:成功/失败人数原样展示,失败大于 0 时提醒去记录里重发。 */
export function formatNotifyResult(result: NotifyResult): string {
  const base = `成功 ${result.sent} 人,失败 ${result.failed} 人`
  return result.failed > 0 ? `${base},失败的可在通知记录里重发` : base
}

/** 只有失败记录可重发(后端只重发失败记录,成功/待发送重发无意义)。 */
export function canResendNotification(log: ExamNotification): boolean {
  return log.status === '失败'
}

/** 未录完汇总:录分进度里 submitted 小于 total 的班级即未录完班级,
 * 未录完人数为各班 total 与 submitted 之差的和;后端没有按教师维度的
 * 未录完计数接口,这里不把班级/人数冒充成教师数。 */
export function summarizeUnsubmittedScores(progress: ScoreProgress): {
  unsubmittedClasses: number
  unsubmittedStudents: number
} {
  let unsubmittedClasses = 0
  let unsubmittedStudents = 0
  for (const subject of progress.subjects ?? []) {
    for (const cls of subject.classes ?? []) {
      const missing = Math.max(0, cls.total - cls.submitted)
      if (missing > 0) {
        unsubmittedClasses += 1
        unsubmittedStudents += missing
      }
    }
  }
  return { unsubmittedClasses, unsubmittedStudents }
}

// ── 通知设置(KW-57~61):四类开关,默认全开 ──
export const getNotificationSettings = (id: number) =>
  apiGet<NotificationSettings>(`/exam/exams/${id}/notification-settings`)

export function saveNotificationSettings(
  id: number,
  body: {
    schedule_notify_enabled: boolean
    invigilation_remind_enabled: boolean
    score_deadline_remind_enabled: boolean
    publish_notify_enabled: boolean
  },
): Promise<NotificationSettings> {
  return request<NotificationSettings>('PUT', `/exam/exams/${id}/notification-settings`, body)
}

// ── 手动触发四类通知(KW-57~60):只回 sent/failed ──
/** 考试日程通知(KW-57):向班主任和任课教师发钉钉个人通知,不发群消息。 */
export function notifySchedule(id: number): Promise<NotifyResult> {
  return apiPost<NotifyResult>(`/exam/exams/${id}/notify/schedule`, {})
}

/** 监考提醒(KW-58):通知监考教师本人。 */
export function notifyInvigilation(id: number): Promise<NotifyResult> {
  return apiPost<NotifyResult>(`/exam/exams/${id}/notify/invigilation`, {})
}

/** 录分截止提醒(KW-59):向未录完/未提交的教师发催录提醒;未设截止时间后端回 409。 */
export function notifyScoreDeadline(id: number): Promise<NotifyResult> {
  return apiPost<NotifyResult>(`/exam/exams/${id}/notify/score-deadline`, {})
}

/** 成绩发布通知(KW-60):向学生/家长发“已可查询”提醒,不含分数。 */
export function notifyPublish(id: number): Promise<NotifyResult> {
  return apiPost<NotifyResult>(`/exam/exams/${id}/notify/publish`, {})
}

// ── 到期扫(KW-58、KW-59):全校范围;考前一天与当天开考前到点的监考提醒、
// 截止前 24 小时与 2 小时到点的录分催提醒;同一提醒 24 小时内不重复发 ──
export function remindDueNotifications(): Promise<NotifyResult> {
  return apiPost<NotifyResult>('/exam/notifications/remind-due', {})
}

// ── 通知记录与重发(KW-61) ──
export interface ListNotificationsParams {
  type?: string | null
  status?: string | null
  q?: string
}

export function listNotifications(
  id: number,
  params: ListNotificationsParams = {},
): Promise<NotificationList> {
  const qs = new URLSearchParams()
  if (params.type) qs.set('type', params.type)
  if (params.status) qs.set('status', params.status)
  if (params.q) qs.set('q', params.q)
  const suffix = qs.toString()
  return apiGet<NotificationList>(`/exam/exams/${id}/notifications${suffix ? `?${suffix}` : ''}`)
}

/** 重发通知记录:只重发失败记录。 */
export function resendNotification(id: number, nid: number): Promise<ResendResult> {
  return apiPost<ResendResult>(`/exam/exams/${id}/notifications/${nid}/resend`, {})
}

// ── 考试归档、历史对比与备份导出(KW-65~67) ──
// 契约见任务书(与后端 backend/app/api/exam_archive.py、
// backend/app/schemas/exam_archive.py 共用),一个字都不能改:
// 归档只允许已发布成绩的考试(否则后端 409),归档后考试状态变为已归档;
// 取消归档只限 admin/director,取消后考试状态回到已发布成绩;
// 归档包 zip 含参试名单、考场编排、监考表、成绩册、分析报表各一表;
// 历史列表 status 筛选只能是已归档/未归档;两次考试无共同科目时
// subjects 为空并返回 message,前端原样展示;备份导出为多表 Excel 全量导出。
export const ARCHIVE_STATUSES = ['已归档', '未归档'] as const
export type ArchiveStatusFilter = (typeof ARCHIVE_STATUSES)[number]

export interface ArchiveManifestSubjectAvg {
  subject_id: number
  subject_name: string
  avg: number | null
  pass_rate: number
  excellent_rate: number
}

export interface ArchiveManifestPublishBatch {
  scope_type: string
  scope_value: number
  status: string
}

export interface ArchiveManifest {
  exam_id: number
  exam_name: string
  semester_id: number
  participant_count: number
  arrangement_count: number
  invigilation_count: number
  score_count: number
  publish_batches: ArchiveManifestPublishBatch[]
  subject_avgs: ArchiveManifestSubjectAvg[]
  total_avg: number | null
}

export interface ExamArchive {
  archive_id: number
  exam_id: number
  archived_by: number | null
  archived_at: string | null
  manifest: ArchiveManifest
  note: string | null
}

export interface ArchiveItem {
  exam_id: number
  exam_name: string
  exam_type: string
  semester_id: number
  status: string
  archived_at: string | null
  archived_by: number | null
}

export interface ArchiveList {
  items: ArchiveItem[]
  total: number
}

export interface CompareExamRef {
  id: number
  name: string
}

export interface CompareSubject {
  subject_id: number
  subject_name: string
  avg_a: number | null
  avg_b: number | null
  delta_avg: number | null
  pass_rate_a: number | null
  pass_rate_b: number | null
  delta_pass_rate: number | null
  excellent_rate_a: number | null
  excellent_rate_b: number | null
  delta_excellent_rate: number | null
}

export interface ExamCompare {
  exam_a: CompareExamRef
  exam_b: CompareExamRef
  subjects: CompareSubject[]
  total_avg_a: number | null
  total_avg_b: number | null
  delta_total_avg: number | null
  message?: string | null
}

/** 归档后只读提示:归档后考试只读,成绩与考务数据不再修改。 */
export const ARCHIVE_READONLY_HINT = '本次考试已归档，归档后只读，成绩与考务数据不再修改。'

/** 两次考试无共同科目时的提示:后端原样返回,前端必须原样展示,不得改写或省略。 */
export const COMPARE_NO_COMMON_SUBJECT_MESSAGE = '两次考试无共同科目，无法对比'

/** 备份频率与存放位置口径:清单 KW-67 备注原文,由学校信息安全要求决定。 */
export const BACKUP_POLICY_HINT = '备份频率与存放位置由学校信息安全要求决定。'

/** 只有已发布成绩的考试可以归档(与后端 create_archive 的 409 规则一致)。 */
export function canArchiveExam(status: string): boolean {
  return status === '已发布成绩'
}

/** 归档后只读提示:已归档返回提示文案,未归档返回 null。 */
export function archiveReadOnlyHint(archive: ExamArchive | null): string | null {
  return archive ? ARCHIVE_READONLY_HINT : null
}

/** 两次考试无共同科目的提示:有共同科目时返回 null,无共同科目时原样返回后端的 message。 */
export function compareEmptyMessage(compare: ExamCompare): string | null {
  if (compare.subjects.length > 0) return null
  return compare.message ?? COMPARE_NO_COMMON_SUBJECT_MESSAGE
}

/** 变化值展示:空值显示 —,正数带 + 号。 */
export function formatDelta(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return value > 0 ? `+${value}` : String(value)
}

// ── 考试归档(KW-65):一键归档、归档信息、归档包下载、取消归档 ──
export function createArchive(id: number, note?: string | null): Promise<ExamArchive> {
  return apiPost<ExamArchive>(`/exam/exams/${id}/archive`, { note: note ?? null })
}

export const getArchive = (id: number) =>
  apiGet<ExamArchive>(`/exam/exams/${id}/archive`)

export function downloadArchive(id: number): Promise<void> {
  return downloadBlob(`/exam/exams/${id}/archive/download`, 'archive.zip')
}

export function deleteArchive(id: number): Promise<void> {
  return request<void>('DELETE', `/exam/exams/${id}/archive`)
}

// ── 历史考试查询与对比(KW-66):按学期/关键词/归档状态检索,两次考试整体对比 ──
export interface ListArchivesParams {
  semesterId?: number | null
  q?: string
  status?: string | null
}

export function listArchives(params: ListArchivesParams = {}): Promise<ArchiveList> {
  const qs = new URLSearchParams()
  if (params.semesterId != null) qs.set('semester_id', String(params.semesterId))
  if (params.q) qs.set('q', params.q)
  if (params.status) qs.set('status', params.status)
  const suffix = qs.toString()
  return apiGet<ArchiveList>(`/exam/archives${suffix ? `?${suffix}` : ''}`)
}

export function compareArchives(examA: number, examB: number): Promise<ExamCompare> {
  return apiGet<ExamCompare>(`/exam/archives/compare?exam_a=${examA}&exam_b=${examB}`)
}

// ── 数据备份与导出(KW-67):全量导出考务与成绩数据 Excel,前端不解析 ──
export function exportBackup(semesterId?: number | null): Promise<void> {
  const qs = semesterId != null ? `?semester_id=${semesterId}` : ''
  return downloadBlob(`/exam/backup/export${qs}`, 'backup.xlsx')
}
