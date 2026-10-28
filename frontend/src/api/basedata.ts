// 基础资料(教师/科目/场地/班级)API 型别与呼叫封装。

import { apiGet, apiPost, request } from '@/api/client'

export type RoomType = 'normal' | 'special' | 'workshop' | 'outdoor'
export type ClassTrack = 'elementary' | 'junior_high' | 'senior_high' | 'comprehensive' | 'vocational'
export type TeacherRuleType = 'unavailable' | 'avoid' | 'prefer'

export interface SubjectBrief {
  id: number
  name: string
}
export interface Subject {
  id: number
  semester_id: number
  name: string
  domain: string | null
  required_room_type: RoomType | null
  default_block_size: number
  /** 主科(国英数等):自动排课会尽量把主科排在上午 */
  is_major: boolean
}
export interface Teacher {
  id: number
  semester_id: number
  name: string
  base_periods: number
  admin_title: string | null
  admin_reduction: number
  is_external: boolean
  is_active: boolean
  subjects: SubjectBrief[]
  email: string | null
  phone: string | null
  user_id: number | null
  grade_ids: number[]
  is_grade_director: boolean
}
export interface BindableAccount {
  id: number
  username: string
  display_name: string
}
export interface TeacherTimeRule {
  id?: number
  weekday: number
  period_no: number
  rule_type: TeacherRuleType
}
export interface Room {
  id: number
  semester_id: number
  name: string
  room_type: RoomType
  capacity: number | null
  subjects: SubjectBrief[]
}
export interface ClassUnit {
  id: number
  semester_id: number
  grade: number
  name: string
  track: ClassTrack
  department: string | null
  student_count: number | null
  homeroom_teacher_id: number | null
  homeroom_teacher: SubjectBrief | null
  period_table_id: number | null
}

export const ROOM_TYPE_LABELS: Record<RoomType, string> = {
  normal: '普通教室',
  special: '专科教室',
  workshop: '实习工场',
  outdoor: '户外',
}
export const TRACK_LABELS: Record<ClassTrack, string> = {
  elementary: '小学',
  junior_high: '初中',
  senior_high: '普通型高中',
  comprehensive: '综合型高中',
  vocational: '技术型高中',
}
export const RULE_TYPE_LABELS: Record<TeacherRuleType, string> = {
  unavailable: '不可排',
  avoid: '尽量避开',
  prefer: '偏好',
}

// ── 科目 ──
export const listSubjects = (semesterId: number, q?: string) =>
  apiGet<Subject[]>(`/subjects?semester_id=${semesterId}${q ? `&q=${encodeURIComponent(q)}` : ''}`)
export const createSubject = (semesterId: number, body: Partial<Subject>) =>
  apiPost<Subject>(`/subjects?semester_id=${semesterId}`, body)
export const updateSubject = (id: number, body: Partial<Subject>) =>
  request<Subject>('PATCH', `/subjects/${id}`, body)
export const deleteSubject = (id: number) => request<void>('DELETE', `/subjects/${id}`)

// ── 教师 ──
export const listTeachers = (semesterId: number, q?: string) =>
  apiGet<Teacher[]>(`/teachers?semester_id=${semesterId}${q ? `&q=${encodeURIComponent(q)}` : ''}`)
export const createTeacher = (semesterId: number, body: Record<string, unknown>) =>
  apiPost<Teacher>(`/teachers?semester_id=${semesterId}`, body)
export const updateTeacher = (id: number, body: Record<string, unknown>) =>
  request<Teacher>('PATCH', `/teachers/${id}`, body)
export const deleteTeacher = (id: number) => request<void>('DELETE', `/teachers/${id}`)
/** 全体升一年级:本学期全部教师所属年级 7→8、8→9、九年级→七年级(循环带新生) */
export const promoteTeacherGrades = (semesterId: number) =>
  apiPost<{ teachers_updated: number }>(`/teachers/promote-grades?semester_id=${semesterId}`, {})
export const listBindableAccounts = (semesterId: number, currentTeacherId?: number) =>
  apiGet<BindableAccount[]>(
    `/teachers/bindable-accounts?semester_id=${semesterId}` +
      (currentTeacherId ? `&current_teacher_id=${currentTeacherId}` : ''),
  )
/** 教师的登录帐号(事后补开、重设密码;建好即绑定该教师) */
export interface TeacherAccount {
  id: number
  username: string
  display_name: string
  must_change_password: boolean
  is_active: boolean // 停用后无法登录,帐号与历史资料仍保留
}

/** 删除教师会连带失去的东西(删除前先让用户看清楚) */
export interface TeacherDeleteImpact {
  teacher_id: number
  teacher_name: string
  leave_requests: number
  substitutions: number
  assignments: number
  homeroom_classes: number
  account_username: string
}
export const createTeacherAccount = (teacherId: number, username: string, password?: string) =>
  apiPost<TeacherAccount>(`/teachers/${teacherId}/account`, { username, password: password ?? '' })
export const getTeacherAccount = (teacherId: number) =>
  apiGet<TeacherAccount | null>(`/teachers/${teacherId}/account`)
export const setTeacherAccountActive = (teacherId: number, isActive: boolean) =>
  apiPost<TeacherAccount>(`/teachers/${teacherId}/account/active`, { is_active: isActive })
export const getTeacherDeleteImpact = (teacherId: number) =>
  apiGet<TeacherDeleteImpact>(`/teachers/${teacherId}/delete-impact`)
export const resetTeacherPassword = (teacherId: number, password?: string) =>
  apiPost<TeacherAccount>(`/teachers/${teacherId}/account/reset-password`,
    { password: password ?? '' })
export const getTimeRules = (id: number) => apiGet<TeacherTimeRule[]>(`/teachers/${id}/time-rules`)
export const replaceTimeRules = (id: number, rules: TeacherTimeRule[]) =>
  request<TeacherTimeRule[]>('PUT', `/teachers/${id}/time-rules`, rules)

/** 这位教师在草稿/已发布课表中,落在「不可排」时段的一节课。 */
export interface TimeRuleConflict {
  timetable_id: number
  timetable_name: string
  timetable_status: string
  weekday: number
  period_no: number
  text: string // 「周三第二节 701 国文」
}
export const getTimeRuleConflicts = (id: number) =>
  apiGet<TimeRuleConflict[]>(`/teachers/${id}/time-rules/conflicts`)

// ── 场地 ──
export const listRooms = (semesterId: number, q?: string) =>
  apiGet<Room[]>(`/rooms?semester_id=${semesterId}${q ? `&q=${encodeURIComponent(q)}` : ''}`)
export const createRoom = (semesterId: number, body: Record<string, unknown>) =>
  apiPost<Room>(`/rooms?semester_id=${semesterId}`, body)
export const updateRoom = (id: number, body: Record<string, unknown>) =>
  request<Room>('PATCH', `/rooms/${id}`, body)
export const deleteRoom = (id: number) => request<void>('DELETE', `/rooms/${id}`)

// ── 班级 ──
export const listClassUnits = (semesterId: number, q?: string) =>
  apiGet<ClassUnit[]>(
    `/class-units?semester_id=${semesterId}${q ? `&q=${encodeURIComponent(q)}` : ''}`,
  )
export const createClassUnit = (semesterId: number, body: Record<string, unknown>) =>
  apiPost<ClassUnit>(`/class-units?semester_id=${semesterId}`, body)
export const updateClassUnit = (id: number, body: Record<string, unknown>) =>
  request<ClassUnit>('PATCH', `/class-units/${id}`, body)
export const deleteClassUnit = (id: number) => request<void>('DELETE', `/class-units/${id}`)
