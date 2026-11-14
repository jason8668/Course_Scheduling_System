import { describe, expect, it, vi } from 'vitest'
import {
  getClassReportCard,
  getStudentReportCard,
  listTeacherScores,
} from './exam'

// fetch 打桩:记下最后一次请求的 URL;按 URL 回固定 JSON
let lastUrl = ''
vi.stubGlobal('fetch', vi.fn((url: string) => {
  lastUrl = url
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
}))

describe('成绩单与查询 API 客户端(KW-52~54/56)', () => {
  it('个人成绩单与班级成绩单请求路径与参数正确', async () => {
    await getStudentReportCard(3, 11)
    expect(lastUrl).toBe('/api/exam/exams/3/report-cards/student?student_id=11')
    await getClassReportCard(3, 5)
    expect(lastUrl).toBe('/api/exam/exams/3/report-cards/class?class_unit_id=5')
  })

  it('教师端查询请求路径带科目/班级/关键词参数', async () => {
    await listTeacherScores(3, { subjectId: 2, classUnitId: 5, q: '张三' })
    expect(lastUrl).toBe('/api/exam/exams/3/teacher-scores?subject_id=2&class_unit_id=5&q=%E5%BC%A0%E4%B8%89')
    await listTeacherScores(3)
    expect(lastUrl).toBe('/api/exam/exams/3/teacher-scores')
  })
})
