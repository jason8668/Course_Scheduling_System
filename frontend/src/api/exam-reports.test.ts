import { describe, expect, it, vi } from 'vitest'
import {
  PROVISION_ONCE_HINT, applyParentRankVisibility, buildCredentialCsv, getClassReportCard,
  getMyReportCard, getMyScores, getReportSettings, getStudentReportCard, listAccounts,
  listTeacherScores, provisionAccounts, rankVisible, resetAccountPassword, saveReportSettings,
} from './exam'

// fetch 打桩:记下最后一次请求的 URL、方法与 body;按 URL 回固定 JSON
let lastUrl = ''
let lastMethod = ''
let lastBody: unknown = null
vi.stubGlobal('fetch', vi.fn((url: string, init: { method?: string; body?: string } = {}) => {
  lastUrl = url
  lastMethod = init.method ?? 'GET'
  lastBody = init.body ? JSON.parse(init.body) : null
  if (url.startsWith('/api/exam/my-scores')) {
    if (url.includes('exam_id=9')) {
      return Promise.resolve({
        ok: false, status: 403,
        json: () => Promise.resolve({ detail: '本次考试成绩尚未发布' }),
      })
    }
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        items: [{
          exam_id: 3, exam_name: '期中考试', student_id: 11, student_no: '202601',
          student_name: '张三',
          subjects: [{ subject_id: 2, subject_name: '数学', score: 95, status: '正常' }],
          total: 95, class_rank: 1,
        }],
      }),
    })
  }
  if (url.startsWith('/api/exam/accounts/provision')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        students_created: 1, parents_created: 1,
        credentials: [
          { username: '202601', role: 'student', initial_password: 'Ab12345678', student_name: '张三' },
          { username: '13812345678', role: 'parent', initial_password: 'Cd87654321', student_name: '张三' },
        ],
      }),
    })
  }
  if (url.startsWith('/api/exam/accounts/3/reset-password')) {
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ status: 'ok' }) })
  }
  if (url.startsWith('/api/exam/accounts')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        items: [{ user_id: 7, username: '202601', role: 'student', student_names: ['张三'], must_change_password: true }],
        total: 1,
      }),
    })
  }
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
}))

describe('成绩单与查询 API 客户端(KW-52~56)', () => {
  it('my-scores 请求路径与参数正确,未发布 403 的 detail 原样透传', async () => {
    const res = await getMyScores(3)
    expect(lastUrl).toBe('/api/exam/my-scores?exam_id=3')
    expect(lastMethod).toBe('GET')
    expect(res.items[0].student_name).toBe('张三')
    // 排名键缺失即不显示:后端删键,前端不补排名
    expect('grade_rank' in res.items[0]).toBe(false)
    await expect(getMyScores(9)).rejects.toMatchObject({
      status: 403, detail: '本次考试成绩尚未发布',
    })
    expect(lastUrl).toBe('/api/exam/my-scores?exam_id=9')
  })

  it('个人成绩单与班级成绩单请求路径与参数正确', async () => {
    await getMyReportCard(3, 11)
    expect(lastUrl).toBe('/api/exam/my-report-card?exam_id=3&student_id=11')
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

  it('成绩单设置 GET 与 PUT 路径与 body 正确', async () => {
    await getReportSettings(3)
    expect(lastUrl).toBe('/api/exam/exams/3/report-settings')
    await saveReportSettings(3, { parent_show_grade_rank: false, parent_show_class_rank: true })
    expect(lastUrl).toBe('/api/exam/exams/3/report-settings')
    expect(lastMethod).toBe('PUT')
    expect(lastBody).toEqual({ parent_show_grade_rank: false, parent_show_class_rank: true })
  })

  it('账号开通与管理请求路径与参数正确', async () => {
    const res = await provisionAccounts(1)
    expect(lastUrl).toBe('/api/exam/accounts/provision?semester_id=1')
    expect(lastMethod).toBe('POST')
    expect(res.students_created).toBe(1)
    expect(res.credentials).toHaveLength(2)
    await listAccounts({ semesterId: 1, role: 'student', q: '张三' })
    expect(lastUrl).toBe('/api/exam/accounts?semester_id=1&role=student&q=%E5%BC%A0%E4%B8%89')
    await resetAccountPassword(3, 'NewPass123')
    expect(lastUrl).toBe('/api/exam/accounts/3/reset-password')
    expect(lastBody).toEqual({ new_password: 'NewPass123' })
  })

  it('家长版排名按设置隐藏:不显示的键直接删掉,不留 null', () => {
    const card = { student_id: 11, class_rank: 1, grade_rank: 2 }
    // 默认 false/false:两项排名都删掉
    expect(applyParentRankVisibility(card, {
      parent_show_class_rank: false, parent_show_grade_rank: false,
    })).toEqual({ student_id: 11 })
    // 只显示班级排名:年级排名删掉,班级排名保留
    expect(applyParentRankVisibility(card, {
      parent_show_class_rank: true, parent_show_grade_rank: false,
    })).toEqual({ student_id: 11, class_rank: 1 })
    // 两项都显示:原样保留
    expect(applyParentRankVisibility(card, {
      parent_show_class_rank: true, parent_show_grade_rank: true,
    })).toEqual(card)
  })

  it('排名是否显示按后端回传的键在不在判断,键缺失或 null 都不显示', () => {
    expect(rankVisible({ class_rank: 1 }, 'class')).toBe(true)
    expect(rankVisible({}, 'class')).toBe(false)
    expect(rankVisible({ class_rank: null }, 'class')).toBe(false)
    expect(rankVisible({ grade_rank: 2 }, 'grade')).toBe(true)
    expect(rankVisible({ class_rank: 1 }, 'grade')).toBe(false)
  })

  it('初始口令只显示一次的提示文案一字不差', () => {
    expect(PROVISION_ONCE_HINT).toBe('口令只显示一次，请立即分发，关闭后无法再次查看')
  })

  it('分发表 CSV 表头与行正确,角色译为中文,含逗号的学生名加引号', () => {
    const csv = buildCredentialCsv([
      { username: '202601', role: 'student', initial_password: 'Ab12345678', student_name: '张三' },
      { username: '13812345678', role: 'parent', initial_password: 'Cd87654321', student_name: '张三,李四' },
    ])
    const lines = csv.split('\n')
    expect(lines[0]).toBe('用户名,角色,学生,初始口令')
    expect(lines[1]).toBe('202601,学生,张三,Ab12345678')
    expect(lines[2]).toBe('13812345678,家长,"张三,李四",Cd87654321')
  })
})
