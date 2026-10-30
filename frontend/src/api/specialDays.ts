// 特殊日课表 API 型别与呼叫封装。日期皆为 'YYYY-MM-DD'。
// 后端契约:发布(is_active)才参与展开;未填节次沿用主课表;
// 条目 course_assignment_id 为空 = 该节取消;同天同节冲突单次 > 每周 > 每月。

import { apiDelete, apiGet, apiPost, apiPut, request } from '@/api/client'

export type SpecialDayScopeType = 'school' | 'grade'
export type SpecialDayRecurrence = 'single' | 'weekly' | 'monthly'

export interface SpecialDayEntry {
  id: number
  class_unit_id: number
  period_no: number
  course_assignment_id: number | null
}

export interface SpecialDayRule {
  id: number
  semester_id: number
  title: string
  scope_type: SpecialDayScopeType
  scope_id: number | null
  recurrence: SpecialDayRecurrence
  single_date: string | null
  weekday: number | null
  day_of_month: number | null
  start_date: string | null
  end_date: string | null
  is_active: boolean
  entries: SpecialDayEntry[]
}

export interface SpecialDayEntryIn {
  class_unit_id: number
  period_no: number
  course_assignment_id: number | null
}

export interface SpecialDayRuleCreate {
  title: string
  scope_type: SpecialDayScopeType
  scope_id: number | null
  recurrence: SpecialDayRecurrence
  single_date: string | null
  weekday: number | null
  day_of_month: number | null
  start_date: string | null
  end_date: string | null
  entries: SpecialDayEntryIn[]
}

export const SPECIAL_DAY_SCOPE_LABELS: Record<SpecialDayScopeType, string> = {
  school: '全校',
  grade: '年级',
}

export const SPECIAL_DAY_RECURRENCE_LABELS: Record<SpecialDayRecurrence, string> = {
  single: '单次某日',
  weekly: '每周固定周几',
  monthly: '每月固定几号',
}

export const WEEKDAY_LABELS: Record<number, string> = {
  1: '周一',
  2: '周二',
  3: '周三',
  4: '周四',
  5: '周五',
  6: '周六',
  7: '周日',
}

export const listSpecialDayRules = (semesterId: number) =>
  apiGet<SpecialDayRule[]>(`/special-days?semester_id=${semesterId}`)

export const createSpecialDayRule = (semesterId: number, body: SpecialDayRuleCreate) =>
  apiPost<SpecialDayRule>(`/special-days?semester_id=${semesterId}`, body)

export const updateSpecialDayRule = (id: number, body: Partial<SpecialDayRuleCreate>) =>
  request<SpecialDayRule>('PATCH', `/special-days/${id}`, body)

export const replaceSpecialDayEntries = (id: number, entries: SpecialDayEntryIn[]) =>
  apiPut<SpecialDayRule>(`/special-days/${id}/entries`, entries)

export const publishSpecialDayRule = (id: number) =>
  apiPost<SpecialDayRule>(`/special-days/${id}/publish`)

export const unpublishSpecialDayRule = (id: number) =>
  apiPost<SpecialDayRule>(`/special-days/${id}/unpublish`)

export const deleteSpecialDayRule = (id: number) =>
  apiDelete<void>(`/special-days/${id}`)
