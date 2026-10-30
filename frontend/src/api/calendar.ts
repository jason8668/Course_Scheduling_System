// 学校校历(校历事件)API 型别与呼叫封装。
// 后端契约:日期皆为 'YYYY-MM-DD';period_start/period_end 皆 null 表示全天。

import { apiDelete, apiGet, apiPost, request } from '@/api/client'

export type CalendarEventType = 'holiday' | 'activity' | 'exam' | 'other'
export type CalendarScopeType = 'school' | 'grade' | 'class'

export interface CalendarEvent {
  id: number
  semester_id: number
  title: string
  event_type: CalendarEventType
  scope_type: CalendarScopeType
  scope_id: number | null // grade=年级数,class=班级 id,school 时为 null
  start_date: string
  end_date: string
  period_start: number | null
  period_end: number | null
  weekly_recurring: boolean
  note: string | null
  created_by: number | null
  created_at: string
  updated_at: string
}

export interface CalendarEventPayload {
  semester_id: number
  title: string
  event_type: CalendarEventType
  scope_type: CalendarScopeType
  scope_id: number | null
  start_date: string
  end_date: string
  period_start: number | null
  period_end: number | null
  weekly_recurring: boolean
  note: string | null
}

export const CALENDAR_EVENT_TYPE_LABELS: Record<CalendarEventType, string> = {
  holiday: '放假停课',
  activity: '全校活动',
  exam: '考试',
  other: '其他',
}

export const CALENDAR_SCOPE_LABELS: Record<CalendarScopeType, string> = {
  school: '全校',
  grade: '年级',
  class: '班级',
}

export interface Workday {
  date: string
  title: string
  has_copy: boolean
}
export const listWorkdays = (semesterId: number, from?: string, to?: string) => {
  const params = new URLSearchParams({ semester_id: String(semesterId) })
  if (from) params.set('from', from)
  if (to) params.set('to', to)
  return apiGet<Workday[]>(`/calendar-events/workdays?${params.toString()}`)
}

// from/to 皆可省:后端不传范围即返回本学期全部活动(一页一览用)。
export const listCalendarEvents = (semesterId: number, from?: string, to?: string) => {
  const params = new URLSearchParams({ semester_id: String(semesterId) })
  if (from) params.set('from', from)
  if (to) params.set('to', to)
  return apiGet<CalendarEvent[]>(`/calendar-events?${params.toString()}`)
}

export const createCalendarEvent = (body: CalendarEventPayload) =>
  apiPost<CalendarEvent>('/calendar-events', body)

export const updateCalendarEvent = (id: number, body: Partial<CalendarEventPayload>) =>
  request<CalendarEvent>('PATCH', `/calendar-events/${id}`, body)

export const deleteCalendarEvent = (id: number) =>
  apiDelete<void>(`/calendar-events/${id}`)
