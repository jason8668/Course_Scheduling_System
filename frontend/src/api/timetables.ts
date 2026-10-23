// 课表(草稿、格位、冲突检查)API 型别与呼叫封装。

import { apiGet, apiPost, request } from '@/api/client'
import type { PeriodTable } from '@/api/semesters'

export interface ScheduleEntry {
  id: number
  course_assignment_id: number
  weekday: number
  period_no: number
  span: number
  locked: boolean
  subject: string
  teachers: string[]
  classes: string[]
  unit_type: 'single' | 'group' | 'alternate'
  unit_name: string
  room: string | null
  teacher_ids: number[]
  class_ids: number[]
  room_id: number | null
  week_parity?: 'odd' | 'even' | null // 单双周(v1.3.0)
}
export interface TimetableBrief {
  id: number
  semester_id: number
  name: string
  status: string
  entry_count: number
}
export interface Timetable {
  id: number
  semester_id: number
  name: string
  status: string
  entries: ScheduleEntry[]
  stale_affected?: number // 发布后:依旧课表展开、今日之后的调代课数(>0 需重新查看)
}
export interface Conflict {
  code: string
  message: string
}
export interface CheckResponse {
  ok: boolean
  conflicts: Conflict[]
}

// ── 版本管理与发布 ──
export interface UnplacedItem {
  course_assignment_id: number
  subject: string
  classes: string[]
  teachers: string[]
  required: number
  placed: number
  remaining: number
  reason: string  // 自动排课当时 solver 说的「为什么排不下」;手动未排完则为空
}
export interface Completeness {
  required: number
  placed: number
  remaining: number
  complete: boolean
  unplaced: UnplacedItem[]
}

/** 课表检查出来的一项硬约束违规(教师冲堂、落在不可排时段…)。未排完不在此列。 */
export interface CheckIssue {
  code: string
  label: string
  message: string
}
export interface TimetableCheck {
  ok: boolean
  issues: CheckIssue[]
  completeness: Completeness
}

// ── 全员唯读查询 ──
export interface PublicSemester {
  id: number
  label: string
  // 批次#4 新增(可选,后端未回时为 undefined):学期起讫与服务器今天所在周次
  start_date?: string | null
  end_date?: string | null
  current_week_number?: number | null
  current_week_parity?: 'odd' | 'even' | null
}
export interface NamedBrief { id: number; name: string }
export interface PublicClass {
  id: number
  name: string
  grade: number
  period_table_id: number | null
}
export interface PublishedTimetable {
  id: number
  semester_id: number
  semester_label: string
  name: string
  status: string
  entries: ScheduleEntry[]
  classes: PublicClass[]
  teachers: NamedBrief[]
  rooms: NamedBrief[]
  period_tables: PeriodTable[]
}

export const STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  published: '已发布',
  archived: '已封存',
}

export const listTimetables = (semesterId: number) =>
  apiGet<TimetableBrief[]>(`/timetables?semester_id=${semesterId}`)
export const createTimetable = (semesterId: number, name: string) =>
  apiPost<Timetable>(`/timetables?semester_id=${semesterId}`, { name })
export const getTimetable = (id: number) => apiGet<Timetable>(`/timetables/${id}`)
export const deleteTimetable = (id: number) => request<void>('DELETE', `/timetables/${id}`)

export const checkConflict = (
  timetableId: number,
  body: {
    course_assignment_id: number
    weekday: number
    period_no: number
    span?: number
    ignore_entry_id?: number
  },
) => apiPost<CheckResponse>(`/timetables/${timetableId}/check-conflict`, body)

export const placeEntry = (
  timetableId: number,
  body: { course_assignment_id: number; weekday: number; period_no: number; span?: number },
) => apiPost<Timetable>(`/timetables/${timetableId}/entries`, body)

export const moveEntry = (
  timetableId: number,
  entryId: number,
  body: { weekday: number; period_no: number },
) => request<Timetable>('PATCH', `/timetables/${timetableId}/entries/${entryId}`, body)

export const deleteEntry = (timetableId: number, entryId: number) =>
  request<void>('DELETE', `/timetables/${timetableId}/entries/${entryId}`)

export const lockEntry = (timetableId: number, entryId: number, locked: boolean) =>
  apiPost<Timetable>(`/timetables/${timetableId}/entries/${entryId}/lock?locked=${locked}`)

export const getClassPeriodTable = (classId: number) =>
  apiGet<PeriodTable>(`/class-units/${classId}/period-table`)

export const renameTimetable = (id: number, name: string) =>
  request<Timetable>('PATCH', `/timetables/${id}`, { name })
export const duplicateTimetable = (id: number, name: string) =>
  apiPost<Timetable>(`/timetables/${id}/duplicate`, { name })
export const getCompleteness = (id: number) =>
  apiGet<Completeness>(`/timetables/${id}/completeness`)
export const checkTimetable = (id: number) => apiGet<TimetableCheck>(`/timetables/${id}/check`)
export const publishTimetable = (id: number, force = false) =>
  apiPost<Timetable>(`/timetables/${id}/publish${force ? '?force=true' : ''}`)

export const publishedSemesters = () => apiGet<PublicSemester[]>('/published/semesters')
export const getPublishedTimetable = (semesterId: number) =>
  apiGet<PublishedTimetable | null>(`/published/timetable?semester_id=${semesterId}`)
export const getMyTeacher = (semesterId: number) =>
  apiGet<NamedBrief | null>(`/published/my-teacher?semester_id=${semesterId}`)

/** 发布被挡(409)时,detail 内含完整性报告。 */
export function publishReport(detail: unknown): Completeness | null {
  if (detail && typeof detail === 'object' && 'completeness' in detail) {
    return (detail as { completeness: Completeness }).completeness
  }
  return null
}

/** 发布被挡(409)时,detail 内的违规清单(没有违规、只是未排完时为空阵列)。 */
export function publishIssues(detail: unknown): CheckIssue[] {
  if (detail && typeof detail === 'object' && 'issues' in detail) {
    return (detail as { issues: CheckIssue[] }).issues ?? []
  }
  return []
}

/** place/move 失败时后端回 409,detail 可能是字串或 { message, conflicts }。 */
export function conflictText(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && 'conflicts' in detail) {
    const d = detail as { message?: string; conflicts?: Conflict[] }
    const first = d.conflicts?.[0]?.message
    return first ? first : (d.message ?? '无法排入')
  }
  return '无法排入'
}
