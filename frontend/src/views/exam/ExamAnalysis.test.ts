import { flushPromises, mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { createPinia, setActivePinia } from 'pinia'
import { h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import {
  PROGRESS_NO_PREV_MESSAGE, createTargetStudent, deleteTargetStudent,
  downloadReportPack, formatPct, getAnalysisCritical, getAnalysisProgress,
  getAnalysisRankings, getAnalysisSegments, getAnalysisSettings, getAnalysisSummary,
  getGradeDistribution, getQualityCompare, getStudentTrend, getTargetTracking,
  listGradeBands, listSubjectThresholds, listTargetStudents, nextRankAfterTie,
  progressEmptyMessage, saveAnalysisSettings, saveGradeBands, saveSubjectThresholds,
  tieGroups, tieRuleHint,
} from '@/api/exam'
import type { AnalysisProgress, RankingItem } from '@/api/exam'
import ExamAnalysis from './ExamAnalysis.vue'
import { useAuthStore } from '@/stores/auth'

// fetch 打桩:记下最后一次请求的 URL、方法与 body;按 URL 回固定 JSON
let lastUrl = ''
let lastMethod = ''
let lastBody: unknown = null
// 质量对比默认回 200;挂载测试里把它切成 403,验证 403 原样展示。
let qualityCompareForbidden = false
vi.stubGlobal('fetch', vi.fn((url: string, init: { method?: string; body?: string } = {}) => {
  lastUrl = url
  lastMethod = init.method ?? 'GET'
  lastBody = init.body ? JSON.parse(init.body) : null
  if (url === '/api/exam/exams/3') {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        id: 3, semester_id: 1, name: '期中考试', exam_type: '期中', grades: [7],
        status: '成绩处理中', description: null, created_at: '2026-11-01',
        subjects: [{ subject_id: 2, subject_name: '数学', exam_date: null, start_time: null, end_time: null, full_score: 120 }],
        participant_count: 40,
      }),
    })
  }
  if (url.startsWith('/api/class-units')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve([
        { id: 5, semester_id: 1, grade: 7, name: '七年二班', track: '普通', department: null, student_count: 40, homeroom_teacher_id: null },
      ]),
    })
  }
  if (url.startsWith('/api/exam/exams/3/participants')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        items: [{
          id: 1, exam_id: 3, student_id: 11, student_no: '202601', student_name: '张三',
          class_unit_id: 5, class_name: '七年二班', grade: 7, status: '正常', note: null,
        }],
        total: 1,
      }),
    })
  }
  if (url.startsWith('/api/exam/exams/3/analysis-settings')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        exam_id: 3, rank_tie_rule: 'dense', segment_size: 10,
        critical_total_line: 300, critical_margin: 5, subject_critical_margin: 5,
      }),
    })
  }
  if (url.startsWith('/api/exam/exams/3/subject-thresholds')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        items: [{ id: 1, exam_id: 3, subject_id: 2, subject_name: '数学', pass_line: 72, excellent_line: 102 }],
      }),
    })
  }
  if (url.startsWith('/api/exam/exams/3/analysis/summary')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        scope: 'grade',
        totals: { count: 40, avg: 320.5, max: 480, min: 120, std: 45.2 },
        subjects: [{
          subject_id: 2, subject_name: '数学', count: 40, avg: 85.5, max: 118, min: 30,
          std: 12.3, pass_rate: 80, excellent_rate: 25, low_rate: 5,
        }],
      }),
    })
  }
  if (url.startsWith('/api/exam/exams/3/analysis/rankings')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        items: [
          { student_id: 11, student_no: '202601', student_name: '张三', class_name: '七年二班', total: 480, rank: 1 },
          { student_id: 12, student_no: '202602', student_name: '李四', class_name: '七年二班', total: 480, rank: 1 },
          { student_id: 13, student_no: '202603', student_name: '王五', class_name: '七年二班', total: 470, rank: 2 },
        ],
        total: 3,
      }),
    })
  }
  if (url.startsWith('/api/exam/exams/3/analysis/segments')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        segments: [
          { label: '470-480', count: 2, pct: 66.67 },
          { label: '460-470', count: 1, pct: 33.33 },
        ],
      }),
    })
  }
  if (url.startsWith('/api/exam/exams/3/analysis/critical')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        items: [{
          student_id: 13, student_no: '202603', student_name: '王五', class_name: '七年二班',
          total: 298, gap_to_line: -2, subject_gaps: [{ subject_name: '数学', score: 70, gap: -2 }],
        }],
      }),
    })
  }
  if (url.startsWith('/api/exam/exams/3/analysis/target-tracking')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        items: [{
          student_id: 11, student_no: '202601', student_name: '张三', class_name: '七年二班',
          target_total: 450, total: 480, reached: true, weak_subjects: [],
        }],
      }),
    })
  }
  if (url.startsWith('/api/exam/exams/3/target-students')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        items: [{
          id: 1, exam_id: 3, student_id: 11, student_no: '202601', student_name: '张三',
          class_name: '七年二班', target_total: 450, note: null,
        }],
      }),
    })
  }
  if (url.startsWith('/api/exam/exams/3/analysis/progress')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        items: [], top_improved: [], top_declined: [],
        message: '暂无上次同类考试，无法对比',
      }),
    })
  }
  if (url.startsWith('/api/exam/exams/3/analysis/quality-compare')) {
    if (qualityCompareForbidden) {
      return Promise.resolve({
        ok: false, status: 403,
        json: () => Promise.resolve({ detail: '质量对比仅对管理角色开放' }),
      })
    }
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({ subjects: [], classes: [] }),
    })
  }
  if (url.startsWith('/api/exam/exams/3/analysis/trend')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        student_id: 11, student_name: '张三',
        exams: [{ exam_id: 2, exam_name: '月考', exam_date: '2026-10-10', total: 460, subjects: { 数学: 88 } }],
      }),
    })
  }
  if (url.startsWith('/api/exam/exams/3/grade-bands')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        items: [{ id: 1, exam_id: 3, subject_id: null, grade_label: 'A', min_score: 90, max_score: 120 }],
      }),
    })
  }
  if (url.startsWith('/api/exam/exams/3/analysis/grade-distribution')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({ bands: [{ grade_label: 'A', count: 10, pct: 25 }] }),
    })
  }
  if (url.startsWith('/api/exam/exams/3/analysis/report-pack')) {
    return Promise.resolve({
      ok: true, status: 200,
      headers: { get: () => null },
      blob: () => Promise.resolve(new Blob(['x'])),
    })
  }
  return Promise.resolve({
    ok: true, status: 200,
    json: () => Promise.resolve({ items: [], total: 0 }),
  })
}))

describe('成绩分析 API 客户端(KW-41~51)', () => {
  it('分析设置查询与保存走 /analysis-settings,带全部五项口径', async () => {
    await getAnalysisSettings(3)
    expect(lastUrl).toBe('/api/exam/exams/3/analysis-settings')
    await saveAnalysisSettings(3, {
      rank_tie_rule: 'competition', segment_size: 5,
      critical_total_line: 300, critical_margin: 10, subject_critical_margin: 3,
    })
    expect(lastUrl).toBe('/api/exam/exams/3/analysis-settings')
    expect(lastMethod).toBe('PUT')
    expect(lastBody).toMatchObject({
      rank_tie_rule: 'competition', segment_size: 5,
      critical_total_line: 300, critical_margin: 10, subject_critical_margin: 3,
    })
    await saveAnalysisSettings(3, {
      rank_tie_rule: 'dense', segment_size: 10, critical_margin: 5, subject_critical_margin: 5,
    })
    expect(lastBody).toMatchObject({ critical_total_line: null })
  })

  it('科目阈值查询与保存走 /subject-thresholds,空线存 null', async () => {
    await listSubjectThresholds(3)
    expect(lastUrl).toBe('/api/exam/exams/3/subject-thresholds')
    await saveSubjectThresholds(3, [{ subject_id: 2, pass_line: 72, excellent_line: 102 }])
    expect(lastUrl).toBe('/api/exam/exams/3/subject-thresholds')
    expect(lastMethod).toBe('PUT')
    expect(lastBody).toMatchObject({
      items: [{ subject_id: 2, pass_line: 72, excellent_line: 102 }],
    })
    await saveSubjectThresholds(3, [{ subject_id: 2 }])
    expect(lastBody).toMatchObject({ items: [{ subject_id: 2, pass_line: null, excellent_line: null }] })
  })

  it('汇总带 scope/grade/class_unit_id 参数', async () => {
    await getAnalysisSummary(3)
    expect(lastUrl).toBe('/api/exam/exams/3/analysis/summary?scope=grade')
    await getAnalysisSummary(3, { scope: 'class', grade: 7, classUnitId: 5 })
    expect(lastUrl).toBe('/api/exam/exams/3/analysis/summary?scope=class&grade=7&class_unit_id=5')
  })

  it('排名带 scope/subject_id/grade/class_unit_id 参数,总分不带 subject_id', async () => {
    await getAnalysisRankings(3, { subjectId: 2, grade: 7 })
    expect(lastUrl).toBe('/api/exam/exams/3/analysis/rankings?scope=grade&subject_id=2&grade=7')
    await getAnalysisRankings(3, { scope: 'class', classUnitId: 5 })
    expect(lastUrl).toBe('/api/exam/exams/3/analysis/rankings?scope=class&class_unit_id=5')
  })

  it('分数段带 subject_id/scope/grade/class_unit_id 参数', async () => {
    await getAnalysisSegments(3)
    expect(lastUrl).toBe('/api/exam/exams/3/analysis/segments?scope=grade')
    await getAnalysisSegments(3, { subjectId: 2, scope: 'class', grade: 7, classUnitId: 5 })
    expect(lastUrl).toBe(
      '/api/exam/exams/3/analysis/segments?scope=class&subject_id=2&grade=7&class_unit_id=5',
    )
  })

  it('临界生、目标生跟踪与进退步走固定端点', async () => {
    await getAnalysisCritical(3)
    expect(lastUrl).toBe('/api/exam/exams/3/analysis/critical')
    await getTargetTracking(3)
    expect(lastUrl).toBe('/api/exam/exams/3/analysis/target-tracking')
    await getAnalysisProgress(3)
    expect(lastUrl).toBe('/api/exam/exams/3/analysis/progress')
  })

  it('目标生查询、新增与删除走 /target-students,删除为 DELETE', async () => {
    await listTargetStudents(3)
    expect(lastUrl).toBe('/api/exam/exams/3/target-students')
    await createTargetStudent(3, { student_id: 11, target_total: 450, note: '冲刺班' })
    expect(lastUrl).toBe('/api/exam/exams/3/target-students')
    expect(lastMethod).toBe('POST')
    expect(lastBody).toMatchObject({ student_id: 11, target_total: 450, note: '冲刺班' })
    await createTargetStudent(3, { student_id: 12 })
    expect(lastBody).toMatchObject({ student_id: 12, target_total: null, note: null })
    await deleteTargetStudent(3, 1)
    expect(lastUrl).toBe('/api/exam/exams/3/target-students/1')
    expect(lastMethod).toBe('DELETE')
  })

  it('质量对比带 grade 参数,个人趋势带 student_id 参数', async () => {
    await getQualityCompare(3, 7)
    expect(lastUrl).toBe('/api/exam/exams/3/analysis/quality-compare?grade=7')
    await getQualityCompare(3)
    expect(lastUrl).toBe('/api/exam/exams/3/analysis/quality-compare')
    await getStudentTrend(3, 11)
    expect(lastUrl).toBe('/api/exam/exams/3/analysis/trend?student_id=11')
  })

  it('等第档查询/保存与等第分布走 /grade-bands 与 /grade-distribution', async () => {
    await listGradeBands(3)
    expect(lastUrl).toBe('/api/exam/exams/3/grade-bands')
    await listGradeBands(3, 2)
    expect(lastUrl).toBe('/api/exam/exams/3/grade-bands?subject_id=2')
    await saveGradeBands(3, [{ subject_id: null, grade_label: 'A', min_score: 90, max_score: 120 }])
    expect(lastUrl).toBe('/api/exam/exams/3/grade-bands')
    expect(lastMethod).toBe('PUT')
    expect(lastBody).toMatchObject({
      items: [{ subject_id: null, grade_label: 'A', min_score: 90, max_score: 120 }],
    })
    await getGradeDistribution(3, 2)
    expect(lastUrl).toBe('/api/exam/exams/3/analysis/grade-distribution?subject_id=2')
    await getGradeDistribution(3)
    expect(lastUrl).toBe('/api/exam/exams/3/analysis/grade-distribution')
  })

  it('报表包下载走 /analysis/report-pack', async () => {
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:report'),
      revokeObjectURL: vi.fn(),
    })
    await downloadReportPack(3)
    expect(lastUrl).toBe('/api/exam/exams/3/analysis/report-pack')
  })
})

describe('排名并列两种规则的展示逻辑(KW-42)', () => {
  const tied: RankingItem[] = [
    { student_id: 11, student_no: '202601', student_name: '张三', class_name: '七年二班', total: 480, rank: 1 },
    { student_id: 12, student_no: '202602', student_name: '李四', class_name: '七年二班', total: 480, rank: 1 },
    { student_id: 13, student_no: '202603', student_name: '王五', class_name: '七年二班', total: 470, rank: 2 },
  ]

  it('dense:同分同名次,下一名次连续', () => {
    expect(tieRuleHint('dense')).toContain('同分同名次')
    expect(tieRuleHint('dense')).toContain('下一名次为第 2 名')
    expect(nextRankAfterTie('dense', 1, 2)).toBe(2)
    expect(nextRankAfterTie('dense', 3, 4)).toBe(4)
  })

  it('competition:同分并列占位,下一名次按并列人数跳过', () => {
    expect(tieRuleHint('competition')).toContain('同分并列占位')
    expect(tieRuleHint('competition')).toContain('下一名次为第 3 名')
    expect(nextRankAfterTie('competition', 1, 2)).toBe(3)
    expect(nextRankAfterTie('competition', 3, 4)).toBe(7)
  })

  it('并列组按名次与总分归组,同分不同名次不混组', () => {
    const groups = tieGroups(tied)
    expect(groups).toHaveLength(2)
    expect(groups[0]).toMatchObject({ rank: 1, total: 480, count: 2 })
    expect(groups[1]).toMatchObject({ rank: 2, total: 470, count: 1 })
    expect(tieGroups([])).toEqual([])
  })
})

describe('进退步无上次考试提示的原样展示逻辑(KW-47)', () => {
  it('后端 message 与前端常量一致,不得改写', () => {
    expect(PROGRESS_NO_PREV_MESSAGE).toBe('暂无上次同类考试，无法对比')
  })

  it('无上次考试时原样返回 message,有数据时返回 null', () => {
    const empty: AnalysisProgress = {
      items: [], top_improved: [], top_declined: [], message: '暂无上次同类考试，无法对比',
    }
    expect(progressEmptyMessage(empty)).toBe('暂无上次同类考试，无法对比')
    const noMessage: AnalysisProgress = { items: [], top_improved: [], top_declined: [] }
    expect(progressEmptyMessage(noMessage)).toBe(PROGRESS_NO_PREV_MESSAGE)
    const withData: AnalysisProgress = {
      items: [{
        student_id: 11, student_no: '202601', student_name: '张三', class_name: '七年二班',
        prev_total: 460, total: 480, prev_rank: 5, rank: 1, delta: 4,
      }],
      top_improved: [], top_declined: [], message: '暂无上次同类考试，无法对比',
    }
    expect(progressEmptyMessage(withData)).toBeNull()
  })

  it('百分比直接展示后端 0~100 数值,不再乘 100', () => {
    expect(formatPct(80)).toBe('80%')
    expect(formatPct(66.67)).toBe('66.67%')
    expect(formatPct(null)).toBe('—')
  })
})

describe('成绩分析页分区渲染', () => {
  it('十一个分区标题齐全,汇总与排名展示后端数据,无上次考试提示原样展示,质量对比 403 原样展示', async () => {
    qualityCompareForbidden = true
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    auth.user = {
      id: 1, username: 'admin', display_name: '系统管理员', roles: ['admin'],
      must_change_password: false,
    }
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/exam/exams/:id', name: 'exam-exam-detail', component: { template: '<div />' } },
        { path: '/exam/exams/:id/analysis', name: 'exam-exam-analysis', component: ExamAnalysis },
      ],
    })
    await router.push('/exam/exams/3/analysis')
    await router.isReady()
    const Host = { render: () => h(NMessageProvider, () => h(ExamAnalysis)) }
    const wrapper = mount(Host, { global: { plugins: [pinia, router] } })
    await flushPromises()
    await flushPromises()
    await flushPromises()
    const text = wrapper.text()
    for (const title of [
      '分析设置', '科目及格优秀线', '等第档', '汇总', '排名', '分数段分布',
      '临界生', '目标生跟踪', '进退步分析', '学科与班级质量对比', '学生个人成绩趋势',
      '等第分布', '报表包导出',
    ]) {
      expect(text).toContain(title)
    }
    expect(text).toContain('期中考试 · 成绩分析')
    // 汇总:总分与数学及格率直接展示后端 0~100 数值
    expect(text).toContain('共 40 人')
    expect(text).toContain('80%')
    // 排名:同分同名次,第 1 名并列 2 人,下一名次为第 2 名,并列标记出现
    expect(text).toContain('张三')
    expect(wrapper.find('[data-testid="analysis-rank-tie-note"]').text()).toContain('下一名次为第 2 名')
    expect(text).toContain('并列')
    // 临界生与目标生跟踪
    expect(text).toContain('王五')
    expect(text).toContain('已达标')
    // 进退步:后端 message 原样展示,一字不改
    const progressAlert = wrapper.find('[data-testid="analysis-progress-empty"]')
    expect(progressAlert.exists()).toBe(true)
    expect(progressAlert.text()).toBe('暂无上次同类考试，无法对比')
    // 质量对比:后端 403 的 detail 原样展示
    const qualityAlert = wrapper.find('[data-testid="analysis-quality-forbidden"]')
    expect(qualityAlert.exists()).toBe(true)
    expect(qualityAlert.text()).toBe('质量对比仅对管理角色开放')
    // 打印与报表包按钮在场
    expect(wrapper.find('[data-testid="analysis-print-btn"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="analysis-export-report-pack"]').exists()).toBe(true)
  })
})
