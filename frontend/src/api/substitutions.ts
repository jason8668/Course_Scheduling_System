// 调代课处理:代课推荐、指派处置(M4-2)、可对调节次(v1.2.1)、通知单(v1.2.2/v1.2.5)。

import { apiDelete, apiGet, apiPost, apiPut } from '@/api/client'

export interface Candidate {
  teacher_id: number
  teacher_name: string
  same_grade: boolean
  same_subject: boolean
  at_school_that_day: boolean
  sub_periods_this_month: number
  reasons: string[]
}

export interface Recommendation {
  affected_period_id: number
  candidates: Candidate[]
  no_candidate_hint: string
}

export interface Substitution {
  id: number
  affected_period_id: number
  type: string
  type_label: string
  handler_teacher_id: number | null
  handler_name: string | null
  counts_toward_hours: boolean
  funding_source: string
  swap_date: string | null
  swap_period_name: string
  swap_class_names: string
  swap_subject_name: string
  created_by_name: string
}

/** 乙的某一节课、在某一天,可改由请假的甲来补 */
export interface SwapOption {
  entry_id: number
  date: string
  weekday: number
  period_no: number
  period_name: string
  class_names: string
  subject_name: string
  same_class: boolean // 与请假那节同一班(同班互调)
  in_block: boolean // 连堂中的一节(只换这一节)
}

export interface SwapPartner {
  teacher_id: number
  teacher_name: string
  teaches_same_class: boolean
  blocked_reason: string // 非空 = 这位老师在请假那节就来不了
  options: SwapOption[]
}

export interface SwapOptions {
  affected_period_id: number
  date_from: string
  date_to: string
  partners: SwapPartner[]
}

export interface AssignBody {
  type: string
  handler_teacher_id?: number | null
  counts_toward_hours?: boolean | null
  funding_source?: string
  swap_entry_id?: number | null
  swap_date?: string | null
  swap_period_no?: number | null // 连堂格位换其中哪一节
}

export const listSubstitutionTypes = (): Promise<Record<string, string>> =>
  apiGet('/substitution-types')

export const getRecommendations = (affectedId: number): Promise<Recommendation> =>
  apiGet(`/affected-periods/${affectedId}/recommendations`)

export const assignSubstitution = (affectedId: number, body: AssignBody): Promise<Substitution> =>
  apiPut(`/affected-periods/${affectedId}/substitution`, body)

/** 整批指派代课:一张假单(或其中一天)还没处理的节次,全部派给同一位老师。 */
export interface BatchAssignBody {
  handler_teacher_id: number
  funding_source?: string
  counts_toward_hours?: boolean | null
  date?: string | null // 空 = 整张假单
}
export interface BatchSkip {
  affected_period_id: number
  date: string
  period_name: string
  class_names: string
  subject_name: string
  reason: string
}
export interface BatchAssignResult {
  assigned: number
  skipped: BatchSkip[]
}
export const assignSubstitutionBatch = (
  leaveId: number, body: BatchAssignBody,
): Promise<BatchAssignResult> => apiPost(`/leaves/${leaveId}/substitutions/batch`, body)

export const clearSubstitution = (affectedId: number): Promise<{ status: string }> =>
  apiDelete(`/affected-periods/${affectedId}/substitution`)

/** 未指定教师时,只找也教这个班的老师;weeks = 从请假那周起找几周(1–4) */
export const getSwapOptions = (
  affectedId: number, teacherId?: number | null, weeks = 2,
): Promise<SwapOptions> => {
  const q = new URLSearchParams({ weeks: String(weeks) })
  if (teacherId) q.set('teacher_id', String(teacherId))
  return apiGet(`/affected-periods/${affectedId}/swap-options?${q}`)
}

// ── 通知单(调课单 v1.2.2、代课单 v1.2.5;两者版面相同,表头与格子内容不同)──

export interface SlipRow {
  ordinal: number // 第几节(只数一般课)
  start_time: string | null
  end_time: string | null
  afternoon_starts: boolean // 下午第一节:纸本在这里画粗线
}

export interface SlipCell {
  date: string
  weekday: number
  ordinal: number
  subject_name: string
  actor: string // 第三行:调课单写上课老师;代课单写「班级[代]」或「老师[代]」
  code: string // 「调09-15_25」:与 9/15 星期二第 5 节对调;代课单没有
  time_note?: string // 跨节次表的格子:实际上课时间(与格线那一列不同时才有)
}

export interface SlipWeek {
  monday: string
  days: string[]
  cells: SlipCell[]
}

export interface Slip {
  kind: 'teacher' | 'class'
  teacher_name: string
  class_names: string
  date_from: string
  date_to: string
  absent_teacher_name: string // 代课单:请假教师
  leave_type_name: string // 代课单:假别
  funding_label: string // 代课单:计费方式
  rows: SlipRow[]
  weeks: SlipWeek[]
}

export interface Slips {
  title: string
  kind: 'swap' | 'substitute'
  slips: Slip[]
}

const slipsQuery = (semesterId: number, affectedIds: number[]): string => {
  const q = new URLSearchParams({ semester_id: String(semesterId) })
  for (const id of affectedIds) q.append('affected_period_ids', String(id))
  return String(q)
}

export const getSwapSlips = (semesterId: number, affectedIds: number[]): Promise<Slips> =>
  apiGet(`/swap-slips?${slipsQuery(semesterId, affectedIds)}`)

export const getSubstituteSlips = (semesterId: number, affectedIds: number[]): Promise<Slips> =>
  apiGet(`/substitute-slips?${slipsQuery(semesterId, affectedIds)}`)

export const listFundingSources = (): Promise<string[]> =>
  apiGet('/substitution-funding-sources')

/** 在新分页开启通知单(打印页不套侧边栏);kind 决定印调课单还是代课单 */
export function openSlips(
  kind: 'swap' | 'substitute', semesterId: number, affectedIds: number[],
): void {
  const path = kind === 'swap' ? '/swap-slips/print' : '/substitute-slips/print'
  window.open(`${path}?semester_id=${semesterId}&ids=${affectedIds.join(',')}`, '_blank')
}
