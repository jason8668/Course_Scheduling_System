// 教师实际上课课时查询(仪表板 + 管理员查询/打印共用)。
// 口径与后端一致:已发布课表按日期展开、叠加请假调代课、未来日期不计入「已上」。

import { apiGet } from '@/api/client'

export interface TeacherHours {
  teacher_id: number
  teacher_name: string
  total: number
  by_grade: Record<string, number>
  substitute_total: number
}

export interface TeachingHoursReport {
  semester_id: number
  date_from: string
  date_to: string
  effective_from: string
  effective_to: string
  teachers: TeacherHours[]
  total_periods: number
}

export type HoursScope = 'week' | 'semester' | 'custom'

export interface HoursQuery {
  semester_id: number
  scope: HoursScope
  date_from?: string | null
  date_to?: string | null
  teacher_id?: number | null
  grade?: number | null
}

function qs(q: HoursQuery): string {
  const p = new URLSearchParams({
    semester_id: String(q.semester_id), scope: q.scope,
  })
  if (q.date_from) p.set('date_from', q.date_from)
  if (q.date_to) p.set('date_to', q.date_to)
  if (q.teacher_id) p.set('teacher_id', String(q.teacher_id))
  if (q.grade) p.set('grade', String(q.grade))
  return p.toString()
}

export const getTeachingHours = (q: HoursQuery): Promise<TeachingHoursReport> =>
  apiGet(`/teaching-hours?${qs(q)}`)

export const getMyTeachingHours = (
  semester_id: number, scope: 'month' | 'semester',
): Promise<TeachingHoursReport> =>
  apiGet(`/teaching-hours/mine?semester_id=${semester_id}&scope=${scope}`)
