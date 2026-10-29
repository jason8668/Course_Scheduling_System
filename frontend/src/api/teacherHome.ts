// 教师「我的」页:个人上课提醒自配置。

import { apiGet, apiPut } from '@/api/client'

export interface ReminderPreference {
  bound: boolean
  reminder_enabled: boolean
  reminder_lead_minutes: number | null
  global_lead_minutes: number
  phone: string | null
  dingtalk_bound: boolean
}

export const getReminderPreference = (semesterId: number): Promise<ReminderPreference> =>
  apiGet(`/teachers/me/reminder-preference?semester_id=${semesterId}`)

export const saveReminderPreference = (
  semesterId: number,
  body: { reminder_enabled: boolean, reminder_lead_minutes?: number | null, phone?: string | null },
): Promise<ReminderPreference> =>
  apiPut(`/teachers/me/reminder-preference?semester_id=${semesterId}`, body)
