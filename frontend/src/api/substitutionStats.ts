// 代课课时月结统计(M4-5)。

import { apiGet } from '@/api/client'

export interface StatDetail {
  handler_teacher_id: number
  handler_name: string
  date: string
  period_name: string
  class_names: string
  subject_name: string
  absent_teacher_name: string
  leave_type: string
  leave_type_label: string
  sub_type: string
  sub_type_label: string
  counts_toward_hours: boolean
  funding_source: string
  pay_kind: 'hourly' | 'daily' | 'none' // 课时 / 日薪 / 不计
  daily_shared: boolean // 日薪:当日与其他按日计酬代课老师分担
}

export interface TeacherSummary {
  teacher_id: number
  teacher_name: string
  handled_count: number
  billable_count: number // 课时计费节数(不含日薪)
  daily_days: number // 日薪天数
  daily_periods: number // 日薪那几天共代了几节
  daily_shared_days: number // 其中几天与其他按日计酬代课老师分担
}

export interface MonthlyReport {
  year: number
  month: number
  summaries: TeacherSummary[]
  details: StatDetail[]
}

function qs(sid: number, year: number, month: number, teacherId?: number | null): string {
  const p = new URLSearchParams({
    semester_id: String(sid), year: String(year), month: String(month),
  })
  if (teacherId) p.set('teacher_id', String(teacherId))
  return p.toString()
}

export const getStats = (
  sid: number, year: number, month: number, teacherId?: number | null,
): Promise<MonthlyReport> => apiGet(`/substitution-stats?${qs(sid, year, month, teacherId)}`)

export const getMyStats = (
  sid: number, year: number, month: number,
): Promise<MonthlyReport> => apiGet(`/substitution-stats/mine?${qs(sid, year, month)}`)

export const statsExportUrl = (
  sid: number, year: number, month: number, teacherId?: number | null,
): string => `/api/substitution-stats/export?${qs(sid, year, month, teacherId)}`
