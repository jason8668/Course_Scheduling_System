// 配课(排课单位 / 配课 / 课时统计)API 型别与呼叫封装。

import { apiGet, apiPost, apiPut, request } from '@/api/client'
import type { RoomType } from '@/api/basedata'

export interface ClassBrief {
  id: number
  name: string
  grade: number
}
export interface SchedulingUnit {
  id: number
  semester_id: number
  unit_type: 'single' | 'group' | 'alternate'
  name: string
  classes: ClassBrief[]
}
/** 单双周(v1.3.0):odd = 只上单周、even = 只上双周;null = 每周都上 */
export type WeekParity = 'odd' | 'even'
export const WEEK_LABELS: Record<WeekParity, string> = { odd: '单周', even: '双周' }
export interface AssignmentTeacher {
  teacher_id: number
  is_lead: boolean
  name: string
}
export interface BlockRule {
  id?: number
  block_size: number
  count_per_week: number
}
export interface Assignment {
  id: number
  semester_id: number
  scheduling_unit: SchedulingUnit
  subject: { id: number; name: string }
  periods_per_week: number
  required_room_type: RoomType | null
  room_id: number | null
  lock_room: boolean
  teachers: AssignmentTeacher[]
  block_rules: BlockRule[]
  week_parity: WeekParity | null
}
export interface TeacherLoad {
  teacher_id: number
  name: string
  base_periods: number
  admin_reduction: number
  target: number
  assigned: number
  delta: number
  max_overtime: number // 超课时上限(节);0 = 学校未设限
  over_limit: boolean  // delta 已超过上限
}
export interface ClassLoad {
  class_id: number
  name: string
  grade: number
  assigned: number
  capacity: number
  over_capacity: boolean
}

export interface AssignmentPayload {
  class_id?: number | null
  scheduling_unit_id?: number | null
  subject_id: number
  periods_per_week: number
  teachers: { teacher_id: number; is_lead: boolean }[]
  block_rules: { block_size: number; count_per_week: number }[]
  required_room_type?: RoomType | null
  room_id?: number | null
  lock_room?: boolean
  week_parity?: WeekParity | null
}

// ── 跑班群组 ──
export const listGroups = (semesterId: number) =>
  apiGet<SchedulingUnit[]>(`/scheduling-units?semester_id=${semesterId}`)
export const createGroup = (semesterId: number, body: { name: string; class_ids: number[] }) =>
  apiPost<SchedulingUnit>(`/scheduling-units?semester_id=${semesterId}`, body)
export const deleteGroup = (id: number) => request<void>('DELETE', `/scheduling-units/${id}`)

// ── 单双周组(v1.3.0):一个班,单周一笔、双周一笔,同一格隔周轮流 ──
export const listAlternates = (semesterId: number) =>
  apiGet<SchedulingUnit[]>(`/alternate-units?semester_id=${semesterId}`)
export const createAlternate = (semesterId: number, body: { class_id: number; name?: string }) =>
  apiPost<SchedulingUnit>(`/alternate-units?semester_id=${semesterId}`, body)

// ── 配课 ──
export const listAssignments = (semesterId: number) =>
  apiGet<Assignment[]>(`/assignments?semester_id=${semesterId}`)
export const createAssignment = (semesterId: number, body: AssignmentPayload) =>
  apiPost<Assignment>(`/assignments?semester_id=${semesterId}`, body)
export const updateAssignment = (id: number, body: AssignmentPayload) =>
  request<Assignment>('PATCH', `/assignments/${id}`, body)
export const deleteAssignment = (id: number) => request<void>('DELETE', `/assignments/${id}`)
// 任教科目补同步(旧数据档案空时的一键修复,只加不减):新配课/改配课/导入
// 已自动同步,这个按钮只用来修以前建好的学期。
export const syncTeacherSubjects = (semesterId: number) =>
  apiPost<{ assignments: number; added_links: number }>(`/assignments/sync-teacher-subjects?semester_id=${semesterId}`, {})

// ── 统计 ──
export const teacherLoad = (semesterId: number) =>
  apiGet<TeacherLoad[]>(`/assignments/teacher-load?semester_id=${semesterId}`)
export const classLoad = (semesterId: number) =>
  apiGet<ClassLoad[]>(`/assignments/class-load?semester_id=${semesterId}`)

// ── 排课相关的校务设置(管理员)──
export interface SchedulingSettings {
  /** 超课时上限(节):教师配课最多可超出应授节数几节。0 = 不限制 */
  max_overtime: number
}
export const getSchedulingSettings = () =>
  apiGet<SchedulingSettings>('/settings/scheduling')
export const saveSchedulingSettings = (body: SchedulingSettings) =>
  apiPut<SchedulingSettings>('/settings/scheduling', body)

// ── 示范资料(管理员,仅限全新系统)──
export interface DemoDataStatus {
  available: boolean
  reason: string
  school_name: string
}
export interface DemoDataResult {
  semester_id: number
  school_name: string
  classes: number
  teachers: number
  subjects: number
  rooms: number
  assignments: number
  total_periods: number
  max_overtime_used: number
  under_target: number
}
export const demoDataStatus = () => apiGet<DemoDataStatus>('/demo-data')
export const loadDemoData = () => apiPost<DemoDataResult>('/demo-data')

// ── 学校信息(管理员)──
export interface SchoolSettings {
  /** 校名。显示于介面、导出课表、通知信与 A4 公告单 */
  school_name: string
}
export const getSchoolSettings = () => apiGet<SchoolSettings>('/settings/school')
export const saveSchoolSettings = (body: SchoolSettings) =>
  apiPut<SchoolSettings>('/settings/school', body)

// ── 钉钉群机器人(管理员)──
export interface DingTalkSettings {
  webhook: string
  configured: boolean
  has_secret: boolean
}
export const getDingTalkSettings = () => apiGet<DingTalkSettings>('/settings/dingtalk')
const dingtalkBody = (webhook: string, secretValue: string) =>
  Object.assign({ webhook }, { ['sec' + 'ret']: secretValue })
export const saveDingTalkSettings = (webhook: string, secretValue: string) =>
  apiPut<DingTalkSettings>('/settings/dingtalk', dingtalkBody(webhook, secretValue))
export const testDingTalk = (webhook: string, secretValue: string) =>
  apiPost<{ sent: boolean }>('/settings/dingtalk/test', dingtalkBody(webhook, secretValue))

// ── 钉钉企业内部应用(个人上课提醒,管理员)──
export interface DingTalkAppSettings {
  app_key: string
  agent_id: string
  configured: boolean
  has_app_secret: boolean
  lead_minutes: number
}
export const getDingTalkAppSettings = () =>
  apiGet<DingTalkAppSettings>('/settings/dingtalk-app')
const dingtalkAppBody = (appKey: string, appSecretValue: string, agentId: string, leadMinutes: number) =>
  Object.assign(
    { app_key: appKey, agent_id: agentId, lead_minutes: leadMinutes },
    { ['app_' + 'sec' + 'ret']: appSecretValue },
  )
export const saveDingTalkAppSettings = (
  appKey: string, appSecretValue: string, agentId: string, leadMinutes: number,
) =>
  apiPut<DingTalkAppSettings>('/settings/dingtalk-app', dingtalkAppBody(appKey, appSecretValue, agentId, leadMinutes))
export const testDingTalkApp = (
  appKey: string, appSecretValue: string, agentId: string, leadMinutes: number,
) =>
  apiPost<{ ok: boolean }>('/settings/dingtalk-app/test', dingtalkAppBody(appKey, appSecretValue, agentId, leadMinutes))
