import { describe, expect, it, vi } from 'vitest'
import {
  EXAM_STATUSES,
  addParticipant,
  canAdvanceExamStatus,
  changeExamStatus,
  checkExamSchedule,
  copyExam,
  createExam,
  createSpecialArrangement,
  deleteParticipant,
  deleteSpecialArrangement,
  generateParticipants,
  getExam,
  getPaperInfo,
  isExamDraft,
  isExamStatusBackward,
  listExamSubjects,
  listExams,
  listParticipants,
  listSpecialArrangements,
  nextExamStatus,
  saveExamSubjects,
  savePaperInfo,
  updateExam,
  updateParticipant,
  updateSpecialArrangement,
} from './exam'

// fetch 打桩:记下最后一次请求的 URL、方法与 body,回固定 JSON
let lastUrl = ''
let lastMethod = ''
let lastBody: unknown = null
vi.stubGlobal('fetch', vi.fn((url: string, init: { method?: string; body?: string }) => {
  lastUrl = url
  lastMethod = init.method ?? 'GET'
  lastBody = init.body ? JSON.parse(init.body) : null
  return Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve({ items: [], total: 0, created: 5, skipped: 1, conflicts: [] }),
  })
}))

describe('考试管理 API 客户端(KW-08~14)', () => {
  it('考试列表按契约只带 semester_id/status/q 三个检索参数', async () => {
    await listExams({ semesterId: 1, status: '已发布', q: '期中' })
    expect(lastUrl).toBe('/api/exam/exams?semester_id=1&status=%E5%B7%B2%E5%8F%91%E5%B8%83&q=%E6%9C%9F%E4%B8%AD')
    expect(lastMethod).toBe('GET')
    await listExams({})
    expect(lastUrl).toBe('/api/exam/exams')
  })

  it('新建考试走 POST /exams,详情与修改走 /exams/{id}', async () => {
    await createExam({ semester_id: 1, name: '期中考试', exam_type: '期中', grades: [7, 8], description: '期中' })
    expect(lastUrl).toBe('/api/exam/exams')
    expect(lastMethod).toBe('POST')
    expect(lastBody).toMatchObject({ semester_id: 1, name: '期中考试', exam_type: '期中', grades: [7, 8] })
    await getExam(3)
    expect(lastUrl).toBe('/api/exam/exams/3')
    await updateExam(3, { name: '期中考试(改)', grades: [7] })
    expect(lastUrl).toBe('/api/exam/exams/3')
    expect(lastMethod).toBe('PATCH')
    expect(lastBody).toMatchObject({ name: '期中考试(改)' })
  })

  it('状态流转与复制走契约端点,回退带备注', async () => {
    await changeExamStatus(3, '已发布')
    expect(lastUrl).toBe('/api/exam/exams/3/status')
    expect(lastMethod).toBe('POST')
    expect(lastBody).toMatchObject({ to_status: '已发布' })
    await changeExamStatus(3, '草稿', '日程有误,退回重排')
    expect(lastBody).toMatchObject({ to_status: '草稿', note: '日程有误,退回重排' })
    await copyExam(3, { name: '期中考试(复制)', semester_id: 1 })
    expect(lastUrl).toBe('/api/exam/exams/3/copy')
    expect(lastBody).toMatchObject({ name: '期中考试(复制)', semester_id: 1 })
  })

  it('日程保存走 PUT /subjects,冲突检查走 POST /schedule-check', async () => {
    await listExamSubjects(3)
    expect(lastUrl).toBe('/api/exam/exams/3/subjects')
    await saveExamSubjects(3, [{ subject_id: 2, exam_date: '2026-11-20', start_time: '08:00', end_time: '10:00', full_score: 120 }])
    expect(lastUrl).toBe('/api/exam/exams/3/subjects')
    expect(lastMethod).toBe('PUT')
    expect(lastBody).toMatchObject({ subjects: [{ subject_id: 2, exam_date: '2026-11-20', start_time: '08:00' }] })
    await checkExamSchedule(3)
    expect(lastUrl).toBe('/api/exam/exams/3/schedule-check')
    expect(lastMethod).toBe('POST')
  })

  it('参试名单检索、生成、增补、标记、删除走契约端点', async () => {
    await listParticipants(3, { classUnitId: 5, status: '缺考', q: '张三' })
    expect(lastUrl).toBe('/api/exam/exams/3/participants?class_unit_id=5&status=%E7%BC%BA%E8%80%83&q=%E5%BC%A0%E4%B8%89')
    await generateParticipants(3)
    expect(lastUrl).toBe('/api/exam/exams/3/participants/generate')
    expect(lastMethod).toBe('POST')
    await addParticipant(3, { student_id: 9, note: '借读生' })
    expect(lastUrl).toBe('/api/exam/exams/3/participants')
    expect(lastBody).toMatchObject({ student_id: 9 })
    await updateParticipant(3, 11, { status: '缺考' })
    expect(lastUrl).toBe('/api/exam/exams/3/participants/11')
    expect(lastMethod).toBe('PATCH')
    expect(lastBody).toMatchObject({ status: '缺考' })
    await deleteParticipant(3, 11)
    expect(lastUrl).toBe('/api/exam/exams/3/participants/11')
    expect(lastMethod).toBe('DELETE')
  })

  it('命题信息与特殊安排走契约端点', async () => {
    await getPaperInfo(3)
    expect(lastUrl).toBe('/api/exam/exams/3/paper-info')
    await savePaperInfo(3, [{ subject_id: 2, setter_teacher_id: 4, reviewer_teacher_id: 5, paper_count: 120 }])
    expect(lastUrl).toBe('/api/exam/exams/3/paper-info')
    expect(lastMethod).toBe('PUT')
    expect(lastBody).toMatchObject({ items: [{ subject_id: 2, setter_teacher_id: 4, paper_count: 120 }] })
    await listSpecialArrangements(3)
    expect(lastUrl).toBe('/api/exam/exams/3/special-arrangements')
    await createSpecialArrangement(3, { student_id: 9, arrangement_type: '单独考场', detail: '201 考场' })
    expect(lastUrl).toBe('/api/exam/exams/3/special-arrangements')
    expect(lastBody).toMatchObject({ arrangement_type: '单独考场' })
    await updateSpecialArrangement(3, 7, { detail: '延长 30 分钟' })
    expect(lastUrl).toBe('/api/exam/exams/3/special-arrangements/7')
    expect(lastMethod).toBe('PATCH')
    await deleteSpecialArrangement(3, 7)
    expect(lastUrl).toBe('/api/exam/exams/3/special-arrangements/7')
    expect(lastMethod).toBe('DELETE')
  })

  it('状态流转按钮可见性逻辑:顺序推进、已归档不可推进、回退只认更早状态', () => {
    expect(EXAM_STATUSES).toEqual(['草稿', '已发布', '进行中', '成绩处理中', '已发布成绩', '已归档'])
    expect(nextExamStatus('草稿')).toBe('已发布')
    expect(nextExamStatus('已发布成绩')).toBe('已归档')
    expect(nextExamStatus('已归档')).toBe(null)
    expect(nextExamStatus('未知状态')).toBe(null)
    expect(canAdvanceExamStatus('进行中')).toBe(true)
    expect(canAdvanceExamStatus('已归档')).toBe(false)
    expect(isExamStatusBackward('进行中', '草稿')).toBe(true)
    expect(isExamStatusBackward('进行中', '已发布成绩')).toBe(false)
    expect(isExamStatusBackward('草稿', '草稿')).toBe(false)
    expect(isExamDraft('草稿')).toBe(true)
    expect(isExamDraft('已发布')).toBe(false)
  })
})
