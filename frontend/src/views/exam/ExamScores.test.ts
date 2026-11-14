import { flushPromises, mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { createPinia, setActivePinia } from 'pinia'
import { h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import {
  createMakeup, createMarkingAssignment, createScoreItem, deleteMakeup,
  deleteMarkingAssignment, deleteScoreItem, formatImportErrors, getScoreProgress,
  getScoreSettings, itemizedTotal, listMakeupScores, listMakeups, listMarkingAssignments,
  listScoreItems, listScores, saveMakeupScores, saveScoreSettings, saveScores,
  submitScores, validateItemValue, validateItemizedTotal, validateScore,
} from '@/api/exam'
import ExamScores from './ExamScores.vue'
import { useAuthStore } from '@/stores/auth'

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
    json: () => Promise.resolve({ items: [], total: 0 }),
  })
}))

describe('阅卷与成绩录入 API 客户端(KW-30~35)', () => {
  it('成绩设置按契约走 /score-settings,保存带全部口径字段', async () => {
    await getScoreSettings(3)
    expect(lastUrl).toBe('/api/exam/exams/3/score-settings')
    await saveScoreSettings(3, {
      entry_mode: 'itemized', makeup_mode: 'max', cheating_score_mode: 'null',
      absent_counts: true, score_deadline: '2026-11-20T23:59',
    })
    expect(lastUrl).toBe('/api/exam/exams/3/score-settings')
    expect(lastMethod).toBe('PUT')
    expect(lastBody).toMatchObject({
      entry_mode: 'itemized', makeup_mode: 'max', cheating_score_mode: 'null',
      absent_counts: true, score_deadline: '2026-11-20T23:59',
    })
  })

  it('阅卷分工按科目查、新增带角色与分工范围、删除走 /marking-assignments/{mid}', async () => {
    await listMarkingAssignments(3, 2)
    expect(lastUrl).toBe('/api/exam/exams/3/marking-assignments?subject_id=2')
    await createMarkingAssignment(3, {
      subject_id: 2, teacher_id: 7, role: '阅卷组长', scope_type: '按题', scope_value: '第一大题',
    })
    expect(lastUrl).toBe('/api/exam/exams/3/marking-assignments')
    expect(lastMethod).toBe('POST')
    expect(lastBody).toMatchObject({ subject_id: 2, teacher_id: 7, role: '阅卷组长', scope_type: '按题' })
    await deleteMarkingAssignment(3, 9)
    expect(lastUrl).toBe('/api/exam/exams/3/marking-assignments/9')
    expect(lastMethod).toBe('DELETE')
  })

  it('大题小分按科目查、新增带满分、删除走 /score-items/{iid}', async () => {
    await listScoreItems(3, 2)
    expect(lastUrl).toBe('/api/exam/exams/3/score-items?subject_id=2')
    await createScoreItem(3, { subject_id: 2, name: '第一大题', max_score: 40 })
    expect(lastUrl).toBe('/api/exam/exams/3/score-items')
    expect(lastBody).toMatchObject({ subject_id: 2, name: '第一大题', max_score: 40 })
    await deleteScoreItem(3, 5)
    expect(lastUrl).toBe('/api/exam/exams/3/score-items/5')
    expect(lastMethod).toBe('DELETE')
  })

  it('成绩列表带科目/班级/状态/检索参数,保存走 PUT /scores,提交带科目与班级', async () => {
    await listScores(3, { subjectId: 2, classUnitId: 5, status: '缺考', q: '张三' })
    expect(lastUrl).toBe(
      '/api/exam/exams/3/scores?subject_id=2&class_unit_id=5&status=%E7%BC%BA%E8%80%83&q=%E5%BC%A0%E4%B8%89',
    )
    await saveScores(3, 2, [
      { student_id: 11, score: 88, status: '正常' },
      { student_id: 12, status: '缺考' },
    ])
    expect(lastUrl).toBe('/api/exam/exams/3/scores')
    expect(lastMethod).toBe('PUT')
    expect(lastBody).toMatchObject({
      subject_id: 2,
      scores: [{ student_id: 11, score: 88 }, { student_id: 12, status: '缺考' }],
    })
    await submitScores(3, 2, 5)
    expect(lastUrl).toBe('/api/exam/exams/3/scores/submit')
    expect(lastMethod).toBe('POST')
    expect(lastBody).toMatchObject({ subject_id: 2, class_unit_id: 5 })
  })

  it('进度看板与补考接口按契约走对应路径', async () => {
    await getScoreProgress(3)
    expect(lastUrl).toBe('/api/exam/exams/3/score-progress')
    await listMakeups(3)
    expect(lastUrl).toBe('/api/exam/exams/3/makeups')
    await createMakeup(3, { name: '数学补考', exam_date: '2026-11-25', note: null })
    expect(lastUrl).toBe('/api/exam/exams/3/makeups')
    expect(lastBody).toMatchObject({ name: '数学补考', exam_date: '2026-11-25' })
    await deleteMakeup(3, 4)
    expect(lastUrl).toBe('/api/exam/exams/3/makeups/4')
    expect(lastMethod).toBe('DELETE')
    await listMakeupScores(3, 4, 2)
    expect(lastUrl).toBe('/api/exam/exams/3/makeups/4/scores?subject_id=2')
    await saveMakeupScores(3, 4, 2, [{ student_id: 11, score: 72, status: '正常' }])
    expect(lastUrl).toBe('/api/exam/exams/3/makeups/4/scores')
    expect(lastMethod).toBe('PUT')
    expect(lastBody).toMatchObject({ subject_id: 2, scores: [{ student_id: 11, score: 72 }] })
  })
})

describe('超满分即时校验', () => {
  it('总分超满分或小于 0 报错,空值表示未录不报错', () => {
    expect(validateScore(150, 100)).toBe('分数须在 0 到满分 100 之间')
    expect(validateScore(-1, 100)).toBe('分数须在 0 到满分 100 之间')
    expect(validateScore(100, 100)).toBeNull()
    expect(validateScore(0, 100)).toBeNull()
    expect(validateScore(null, 100)).toBeNull()
    expect(validateScore(undefined, 100)).toBeNull()
  })

  it('大题小分超该题满分报错,小分之和与总分不一致报错', () => {
    const item = { id: 1, exam_id: 3, subject_id: 2, name: '第一大题', max_score: 40, sort_order: 1 }
    expect(validateItemValue(41, item)).toBe('大题「第一大题」小分须在 0 到 40 之间')
    expect(validateItemValue(40, item)).toBeNull()
    expect(validateItemValue(null, item)).toBeNull()
    expect(itemizedTotal([30, 25, null])).toBe(55)
    expect(validateItemizedTotal(56, [30, 25])).toBe('总分须等于小分之和(55),当前总分 56')
    expect(validateItemizedTotal(55, [30, 25])).toBeNull()
  })
})

describe('导入逐行错误展示', () => {
  it('已带“第 N 行:”前缀的不重复加,没带前缀的补上行号', () => {
    expect(formatImportErrors([
      { row: 5, message: '第 5 行:分数须在 0 到满分 100 之间' },
      { row: 7, message: '学号必填' },
    ])).toEqual([
      '第 5 行:分数须在 0 到满分 100 之间',
      '第 7 行: 学号必填',
    ])
  })
})

// ── 组件:超满分即时报错禁保存、导入逐行错误展示 ──
function stubFetchForPage() {
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    if (url.includes('/scores/import')) {
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve({
          created: 0, updated: 0,
          errors: [
            { row: 5, message: '第 5 行:分数须在 0 到满分 100 之间' },
            { row: 7, message: '学号必填' },
          ],
        }),
      })
    }
    if (url.startsWith('/api/exam/exams/3/scores')) {
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve({
          items: [
            { id: 1, exam_id: 3, subject_id: 2, student_id: 11, student_no: '20260101', student_name: '张三', class_name: '701', score: null, status: '正常', submitted: false, items: [] },
            { id: 2, exam_id: 3, subject_id: 2, student_id: 12, student_no: '20260102', student_name: '李四', class_name: '701', score: 88, status: '正常', submitted: false, items: [] },
          ],
          total: 2,
        }),
      })
    }
    if (url.startsWith('/api/exam/exams/3/score-settings')) {
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve({
          exam_id: 3, entry_mode: 'total_only', makeup_mode: 'separate',
          cheating_score_mode: 'zero', absent_counts: false, score_deadline: null,
        }),
      })
    }
    if (url.startsWith('/api/exam/exams/3/score-progress')) {
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve({
          subjects: [{ subject_id: 2, subject_name: '数学', classes: [{ class_unit_id: 5, class_name: '701', total: 2, entered: 1, submitted: 0, status: '录入中' }] }],
        }),
      })
    }
    if (url.startsWith('/api/exam/exams/3/makeups')) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ items: [], total: 0 }) })
    }
    if (url.startsWith('/api/exam/exams/3/marking-assignments') || url.startsWith('/api/exam/exams/3/score-items')) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ items: [], total: 0 }) })
    }
    if (url.startsWith('/api/exam/exams/3')) {
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve({
          id: 3, semester_id: 1, name: '期中考试', exam_type: '期中', grades: [7],
          status: '成绩处理中', description: null, created_at: '2026-11-01',
          subjects: [{ subject_id: 2, subject_name: '数学', exam_date: '2026-11-18', start_time: '08:00', end_time: '10:00', full_score: 100 }],
          participant_count: 2,
        }),
      })
    }
    if (url.startsWith('/api/subjects') || url.startsWith('/api/teachers') || url.startsWith('/api/class-units')) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) })
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
  }))
}

async function mountScores() {
  stubFetchForPage()
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.user = {
    id: 1, username: 'admin', display_name: '系统管理员', roles: ['admin'],
    must_change_password: false,
  } as never
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/exam/exams/:id', name: 'exam-exam-detail', component: { template: '<div />' } },
      { path: '/exam/exams/:id/scores', name: 'exam-exam-scores', component: ExamScores },
    ],
  })
  await router.push('/exam/exams/3/scores')
  await router.isReady()
  const Host = { render: () => h(NMessageProvider, () => h(ExamScores)) }
  const wrapper = mount(Host, {
    global: { plugins: [pinia, router] },
  })
  await flushPromises()
  await flushPromises()
  return wrapper
}

describe('阅卷与成绩录入页', () => {
  it('超满分即时报错并禁用保存,改回合法分数后恢复', async () => {
    const wrapper = mountScores()
    const w = await wrapper
    expect(w.text()).toContain('阅卷与成绩录入')
    expect(w.text()).toContain('张三')
    const input = w.find('[data-testid="score-input-11"]')
    await input.setValue('150')
    expect(w.find('[data-testid="score-error-11"]').text()).toBe('分数须在 0 到满分 100 之间')
    expect(w.find('[data-testid="scores-save"]').attributes('disabled')).toBeDefined()
    await input.setValue('90')
    expect(w.find('[data-testid="score-error-11"]').exists()).toBe(false)
    expect(w.find('[data-testid="scores-save"]').attributes('disabled')).toBeUndefined()
  })

  it('导入失败逐行展示错误,不展示成功提示', async () => {
    const wrapper = mountScores()
    const w = await wrapper
    const file = new File(['x'], 'scores.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    const fileInput = w.find('[data-testid="scores-import-file"]').element as HTMLInputElement
    Object.defineProperty(fileInput, 'files', { value: [file] })
    await w.find('[data-testid="scores-import-file"]').trigger('change')
    await w.find('[data-testid="scores-import"]').trigger('click')
    await flushPromises()
    const box = w.find('[data-testid="scores-import-errors"]')
    expect(box.exists()).toBe(true)
    expect(box.text()).toContain('第 5 行:分数须在 0 到满分 100 之间')
    expect(box.text()).toContain('第 7 行: 学号必填')
    expect(w.find('[data-testid="scores-import-ok"]').exists()).toBe(false)
  })
})
