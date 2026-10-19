// 请假登记与受影响节次(M4-1)。

import { apiGet, apiPost } from '@/api/client'

export interface AffectedPeriod {
  id: number
  date: string
  weekday: number
  period_no: number
  period_name: string // 「第三节」——节次表的名称,不是内部 period_no
  start_time: string | null
  end_time: string | null
  subject_name: string
  class_names: string
  room_name: string
  status: 'pending' | 'resolved' | 'completed' | 'cancelled'
  handler_teacher_id: number | null
  handler_name: string | null
  sub_type: string | null // 已处置时的处置方式(substitute/swap/…)
  swap_date: string | null // 调课才有:请假教师回来补课的日期
  swap_period_name: string
}

export interface LeaveRequest {
  id: number
  semester_id: number
  teacher_id: number
  teacher_name: string
  leave_type: string
  leave_type_label: string
  start_date: string
  start_time: string | null
  end_date: string
  end_time: string | null
  reason: string
  status: 'registered' | 'cancelled'
  created_by_name: string
  created_at: string
  affected_count: number
  pending_count: number
  affected_periods: AffectedPeriod[]
}

export interface LeaveCancelled {
  id: number
  status: string
  revoked_count: number
  notified_teachers: string[]
}

export interface NewLeave {
  teacher_id?: number | null // 组长代登时指定;教师自登留空
  leave_type: string
  start_date: string
  start_time?: string | null
  end_date: string
  end_time?: string | null
  reason?: string
}

export const listLeaveTypes = (): Promise<Record<string, string>> => apiGet('/leave-types')

export const listLeaves = (semesterId: number): Promise<LeaveRequest[]> =>
  apiGet(`/leaves?semester_id=${semesterId}`)

export const createLeave = (semesterId: number, body: NewLeave): Promise<LeaveRequest> =>
  apiPost(`/leaves?semester_id=${semesterId}`, body)

export const cancelLeave = (leaveId: number): Promise<LeaveCancelled> =>
  apiPost(`/leaves/${leaveId}/cancel`)
