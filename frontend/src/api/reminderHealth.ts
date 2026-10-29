// 上课提醒健康状态(只读聚合,管理员):配置、排程任务、最近发送、关提醒与未解析教师。

import { apiGet } from '@/api/client'

export interface ReminderTeacherBrief {
  id: number
  name: string
}

export interface ReminderHealth {
  configured: boolean
  lead_minutes: number
  job_scheduled: boolean | null
  last_sent_at: string | null
  sent_7d: number
  teachers_with_phone: number
  teachers_missing_phone: number
  opted_out: ReminderTeacherBrief[]
  unresolved: ReminderTeacherBrief[]
}

export const getReminderHealth = (): Promise<ReminderHealth> =>
  apiGet('/settings/dingtalk-app/health')
