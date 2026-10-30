// 行政值日 API 型别与呼叫封装。
// 全校共用一位,不算课时;轮值按周几重复,覆盖只影响当天,下周恢复轮值。
// 换班只换当天:值日老师发起,对方同意后生成覆盖。

import { apiDelete, apiGet, apiPost, apiPut } from '@/api/client'

export interface DutyTeacher {
  id: number
  name: string
  admin_title: string | null
}

export interface DutyPattern {
  id: number
  weekday: number
  teacher_id: number
  teacher_name: string | null
}

export interface DutyOverride {
  id: number
  date: string
  teacher_id: number
  teacher_name: string | null
  reason: string | null
}

export interface DutySwapRequest {
  id: number
  date: string
  from_teacher_id: number
  from_teacher_name: string | null
  to_teacher_id: number
  to_teacher_name: string | null
  status: string
}

export interface DutyRoster {
  patterns: DutyPattern[]
  overrides: DutyOverride[]
  swap_requests: DutySwapRequest[]
  eligible: DutyTeacher[]
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

export const getDutyRoster = (semesterId: number) =>
  apiGet<DutyRoster>(`/duty-roster?semester_id=${semesterId}`)

export const setDutyPattern = (semesterId: number, weekday: number, teacherId: number) =>
  apiPut<DutyRoster>(`/duty-roster/pattern?semester_id=${semesterId}`, { weekday, teacher_id: teacherId })

export const setDutyOverride = (semesterId: number, date: string, teacherId: number, reason?: string | null) =>
  apiPut<DutyRoster>(`/duty-roster/override?semester_id=${semesterId}`, { date, teacher_id: teacherId, reason: reason ?? null })

export const deleteDutyOverride = (semesterId: number, date: string) =>
  apiDelete<void>(`/duty-roster/override?semester_id=${semesterId}&date=${date}`)

export const createDutySwapRequest = (semesterId: number, date: string, toTeacherId: number) =>
  apiPost<DutySwapRequest>(`/duty-roster/swap-requests?semester_id=${semesterId}`, { date, to_teacher_id: toTeacherId })

export const approveDutySwap = (id: number) =>
  apiPost<DutySwapRequest>(`/duty-roster/swap-requests/${id}/approve`)

export const rejectDutySwap = (id: number) =>
  apiPost<DutySwapRequest>(`/duty-roster/swap-requests/${id}/reject`)

/** 某天的值日老师名:当天覆盖 > 每周轮值(与后端同一口径)。 */
export function dutyNameForDate(roster: DutyRoster | null, dateStr: string, weekday: number): string | null {
  if (!roster) return null
  const override = roster.overrides.find((o) => o.date === dateStr)
  if (override) return override.teacher_name
  const pattern = roster.patterns.find((p) => p.weekday === weekday)
  return pattern?.teacher_name ?? null
}

/** 某周几的轮值老师名(课表查询/打印的周模板用,无具体日期,故只看轮值)。 */
export function dutyNameForWeekday(roster: DutyRoster | null, weekday: number): string | null {
  if (!roster) return null
  return roster.patterns.find((p) => p.weekday === weekday)?.teacher_name ?? null
}
