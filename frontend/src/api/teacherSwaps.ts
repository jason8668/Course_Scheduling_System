// 老师自主调课 API 型别与呼叫封装。
// 不走请假、不走管理员:发起人必须是原任或换课其中一方,
// 另一方同意即生效;日期可以是过去(事后补登,口头已通知,系统里补记录)。

import { apiGet, apiPost, request } from '@/api/client'

export interface TeacherSwap {
  id: number
  semester_id: number
  requester_id: number
  status: 'pending' | 'approved' | 'rejected'
  note: string | null
  class_date: string
  period_no: number
  class_unit_id: number
  course_assignment_id: number
  original_teacher_id: number
  handler_teacher_id: number
  makeup_date: string | null
  makeup_period_no: number | null
  makeup_class_unit_id: number | null
  makeup_assignment_id: number | null
  approver_teacher_id: number
  is_retroactive: boolean
}

export interface TeacherSwapCreate {
  class_date: string
  period_no: number
  class_unit_id: number
  course_assignment_id: number
  original_teacher_id: number
  handler_teacher_id: number
  makeup_date?: string | null
  makeup_period_no?: number | null
  makeup_class_unit_id?: number | null
  makeup_assignment_id?: number | null
  note?: string | null
}

export const listTeacherSwaps = (semesterId: number) =>
  apiGet<TeacherSwap[]>(`/teacher-swaps?semester_id=${semesterId}`)
export const createTeacherSwap = (semesterId: number, body: TeacherSwapCreate) =>
  apiPost<TeacherSwap>(`/teacher-swaps?semester_id=${semesterId}`, body)
export const approveTeacherSwap = (id: number) =>
  request<TeacherSwap>('POST', `/teacher-swaps/${id}/approve`)
export const rejectTeacherSwap = (id: number) =>
  request<TeacherSwap>('POST', `/teacher-swaps/${id}/reject`)
