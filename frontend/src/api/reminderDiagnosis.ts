// 上课提醒诊断(只读)与测试真发一条(管理员主动点才发)。
import { apiGet, apiPost } from '@/api/client'

export interface DiagnosisStep {
  key: string
  label: string
  status: 'ok' | 'warn' | 'fail'
  detail: string
}

export interface ReminderDiagnosis {
  teacher_id: number
  teacher_name: string
  date: string
  period_no: number
  steps: DiagnosisStep[]
  conclusion: string
}

export const diagnoseReminder = (
  semesterId: number, teacherId: number, on: string, periodNo: number,
): Promise<ReminderDiagnosis> =>
  apiGet(`/settings/dingtalk-app/diagnose?semester_id=${semesterId}&teacher_id=${teacherId}&on=${on}&period_no=${periodNo}`)

export const testSendReminder = (teacherId: number): Promise<{ ok: boolean; teacher_name: string }> =>
  apiPost('/settings/dingtalk-app/test-send', { teacher_id: teacherId })
