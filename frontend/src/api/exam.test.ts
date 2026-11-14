import { describe, expect, it, vi } from 'vitest'
import {
  S_SHAPE_NO_SCORE_WARNING,
  changeStudentStatus,
  createParent,
  createStudent,
  generateExamNumbers,
  getExamNumberRule,
  getStudent,
  listStudents,
  listSubjectSettings,
  maskPhone,
  saveExamNumberRule,
  saveSubjectSettings,
  updateParent,
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
    json: () => Promise.resolve({ items: [], total: 0, generated: 3, warning: '' }),
  })
}))

describe('考务 API 客户端', () => {
  it('学生列表按后端契约带分页与检索参数', async () => {
    await listStudents({ semesterId: 1, grade: 7, classUnitId: 5, q: '张三', status: '在读', limit: 20, offset: 40 })
    expect(lastUrl).toBe(
      '/api/exam/students?semester_id=1&grade=7&class_unit_id=5&q=%E5%BC%A0%E4%B8%89&status=%E5%9C%A8%E8%AF%BB&limit=20&offset=40',
    )
  })

  it('学生详情与新增走 /students/{id} 与 POST /students', async () => {
    await getStudent(9)
    expect(lastUrl).toBe('/api/exam/students/9')
    await createStudent({ semester_id: 1, class_unit_id: 5, student_no: '202601', name: '张三' })
    expect(lastUrl).toBe('/api/exam/students')
    expect(lastMethod).toBe('POST')
    expect(lastBody).toMatchObject({ student_no: '202601', name: '张三' })
  })

  it('状态变更带异动类型、备注与新班级', async () => {
    await changeStudentStatus(9, {
      to_status: '在读', note: '转入七年二班', new_class_unit_id: 6, change_type: '转班',
    })
    expect(lastUrl).toBe('/api/exam/students/9/status')
    expect(lastBody).toMatchObject({ to_status: '在读', change_type: '转班', new_class_unit_id: 6 })
  })

  it('家长新增走学生下路由、修改走 /parents/{id}', async () => {
    await createParent(9, { name: '张父', relation: '父亲', phone: '13812345678' })
    expect(lastUrl).toBe('/api/exam/students/9/parents')
    await updateParent(3, { name: '张父', relation: '父亲', phone: '13900001111' })
    expect(lastUrl).toBe('/api/exam/parents/3')
    expect(lastMethod).toBe('PATCH')
  })

  it('学科分值批量保存走 PUT /subject-settings', async () => {
    await listSubjectSettings(1)
    expect(lastUrl).toBe('/api/exam/subject-settings?semester_id=1')
    await saveSubjectSettings(1, [{
      subject_id: 2, subject_name: '数学', full_score: 120, pass_line: 72,
      excellent_line: 102, counts_toward_total: true, conversion_ratio: 1.0,
    }])
    expect(lastUrl).toBe('/api/exam/subject-settings')
    expect(lastMethod).toBe('PUT')
    expect(lastBody).toMatchObject({
      semester_id: 1,
      settings: [{ subject_id: 2, full_score: 120, pass_line: 72 }],
    })
  })

  it('考号规则查询、保存与生成走同一端点族', async () => {
    await getExamNumberRule(1, 7)
    expect(lastUrl).toBe('/api/exam/exam-number-rule?semester_id=1&grade=7')
    await saveExamNumberRule(1, 7, 's_shape')
    expect(lastUrl).toBe('/api/exam/exam-number-rule')
    expect(lastBody).toMatchObject({ semester_id: 1, grade: 7, rule_type: 's_shape' })
    await generateExamNumbers(1, 7)
    expect(lastUrl).toBe('/api/exam/exam-number-rule/generate')
    expect(lastBody).toMatchObject({ semester_id: 1, grade: 7 })
  })

  it('S 型无成绩警告文案与后端原样一致', () => {
    expect(S_SHAPE_NO_SCORE_WARNING).toBe('暂无上次成绩，暂按学号顺序编排')
  })

  it('家长电话脱敏与后端 mask_phone 同规则', () => {
    expect(maskPhone('13812345678')).toBe('138****5678')
    expect(maskPhone('12345')).toBe('12****45')
    expect(maskPhone('1234')).toBe('****')
    expect(maskPhone(null)).toBe(null)
  })
})
