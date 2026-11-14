import { flushPromises, mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { createPinia, setActivePinia } from 'pinia'
import { h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import {
  ARCHIVE_READONLY_HINT, BACKUP_POLICY_HINT, COMPARE_NO_COMMON_SUBJECT_MESSAGE,
  archiveReadOnlyHint, canArchiveExam, compareArchives, compareEmptyMessage,
  createArchive, deleteArchive, downloadArchive, exportBackup, formatDelta,
  getArchive, listArchives,
} from '@/api/exam'
import type { ExamArchive, ExamCompare } from '@/api/exam'
import ExamArchiveView from './ExamArchive.vue'
import { useAuthStore } from '@/stores/auth'

// fetch 打桩:记下最后一次请求的 URL、方法与 body;按 URL 与模式回固定 JSON
let lastUrl = ''
let lastMethod = ''
let lastBody: unknown = null
let archiveMode: 'none' | 'archived' = 'none'
let compareMode: 'empty' | 'filled' = 'empty'
const seenUrls: string[] = []

const archiveFixture: ExamArchive = {
  archive_id: 1,
  exam_id: 3,
  archived_by: 1,
  archived_at: '2026-11-14T10:00:00',
  manifest: {
    exam_id: 3,
    exam_name: '期中考试',
    semester_id: 1,
    participant_count: 120,
    arrangement_count: 60,
    invigilation_count: 24,
    score_count: 240,
    publish_batches: [{ scope_type: '年级', scope_value: 7, status: '已发布' }],
    subject_avgs: [{ subject_id: 2, subject_name: '数学', avg: 82.5, pass_rate: 85, excellent_rate: 30 }],
    total_avg: 412.5,
  },
  note: '期中归档',
}

const okJson = (data: unknown) => Promise.resolve({
  ok: true, status: 200, json: () => Promise.resolve(data),
})

// jsdom 里 a.click() 会触发导航报错:下载链接点击在此处是无操作桩
vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
vi.stubGlobal('URL', {
  createObjectURL: () => 'blob:fake',
  revokeObjectURL: () => {},
})
vi.stubGlobal('fetch', vi.fn((url: string, init: { method?: string; body?: string } = {}) => {
  lastUrl = url
  seenUrls.push(url)
  lastMethod = init.method ?? 'GET'
  lastBody = init.body ? JSON.parse(init.body) : null
  if (url.includes('/archive/download') || url.includes('/backup/export')) {
    return Promise.resolve({
      ok: true, status: 200,
      headers: { get: () => null },
      blob: () => Promise.resolve(new Blob(['x'])),
    })
  }
  if (url.startsWith('/api/exam/archives/compare')) {
    if (compareMode === 'filled') {
      return okJson({
        exam_a: { id: 3, name: '期中考试' },
        exam_b: { id: 4, name: '月考' },
        subjects: [{
          subject_id: 2, subject_name: '数学', avg_a: 80, avg_b: 85, delta_avg: 5,
          pass_rate_a: 70, pass_rate_b: 75, delta_pass_rate: 5,
          excellent_rate_a: 20, excellent_rate_b: 18, delta_excellent_rate: -2,
        }],
        total_avg_a: 320, total_avg_b: 335, delta_total_avg: 15, message: null,
      })
    }
    return okJson({
      exam_a: { id: 3, name: '期中考试' },
      exam_b: { id: 4, name: '月考' },
      subjects: [],
      total_avg_a: null, total_avg_b: null, delta_total_avg: null,
      message: '两次考试无共同科目，无法对比',
    })
  }
  if (url.startsWith('/api/exam/archives')) {
    return okJson({
      items: [
        {
          exam_id: 3, exam_name: '期中考试', exam_type: '期中', semester_id: 1,
          status: '已归档', archived_at: '2026-11-14T10:00:00', archived_by: 1,
        },
        {
          exam_id: 4, exam_name: '月考', exam_type: '月考', semester_id: 1,
          status: '已发布成绩', archived_at: null, archived_by: null,
        },
      ],
      total: 2,
    })
  }
  if (url === '/api/exam/exams/3/archive') {
    if (lastMethod === 'POST') return okJson(archiveFixture)
    if (lastMethod === 'DELETE') {
      return Promise.resolve({ ok: true, status: 204, json: () => Promise.resolve(undefined) })
    }
    if (archiveMode === 'archived') return okJson(archiveFixture)
    return Promise.resolve({
      ok: false, status: 404,
      json: () => Promise.resolve({ detail: '该考试尚未归档' }),
    })
  }
  if (url === '/api/exam/exams/3') {
    return okJson({
      id: 3, semester_id: 1, name: '期中考试', exam_type: '期中', grades: [7],
      status: archiveMode === 'archived' ? '已归档' : '已发布成绩',
      description: null, created_at: '2026-11-01', subjects: [], participant_count: 120,
    })
  }
  if (url === '/api/semesters') {
    return okJson([{
      id: 1, academic_year: 2026, term: 1, label: '2026 学年上学期',
      status: 'active', start_date: null, end_date: null,
    }])
  }
  return okJson({})
}))

describe('归档备份 API 客户端(KW-65~67)', () => {
  it('一键归档走 POST /exams/{id}/archive,备注可选', async () => {
    await createArchive(3, '期中归档')
    expect(lastUrl).toBe('/api/exam/exams/3/archive')
    expect(lastMethod).toBe('POST')
    expect(lastBody).toMatchObject({ note: '期中归档' })
    await createArchive(3)
    expect(lastBody).toMatchObject({ note: null })
  })

  it('归档查询、下载、取消归档走同一端点族', async () => {
    archiveMode = 'archived'
    await getArchive(3)
    expect(lastUrl).toBe('/api/exam/exams/3/archive')
    expect(lastMethod).toBe('GET')
    await downloadArchive(3)
    expect(lastUrl).toBe('/api/exam/exams/3/archive/download')
    await deleteArchive(3)
    expect(lastUrl).toBe('/api/exam/exams/3/archive')
    expect(lastMethod).toBe('DELETE')
    archiveMode = 'none'
  })

  it('历史档案按学期/关键词/归档状态筛选,无参数时不带查询串', async () => {
    await listArchives({ semesterId: 1, q: '期中', status: '已归档' })
    expect(lastUrl).toBe('/api/exam/archives?semester_id=1&q=%E6%9C%9F%E4%B8%AD&status=%E5%B7%B2%E5%BD%92%E6%A1%A3')
    await listArchives({})
    expect(lastUrl).toBe('/api/exam/archives')
  })

  it('两次考试对比走 /archives/compare,考试 id 作查询参数', async () => {
    await compareArchives(3, 4)
    expect(lastUrl).toBe('/api/exam/archives/compare?exam_a=3&exam_b=4')
    expect(lastMethod).toBe('GET')
  })

  it('全量备份导出走 /backup/export,学期可选', async () => {
    await exportBackup(1)
    expect(lastUrl).toBe('/api/exam/backup/export?semester_id=1')
    await exportBackup()
    expect(lastUrl).toBe('/api/exam/backup/export')
  })
})

describe('归档与对比的展示逻辑(KW-65~67)', () => {
  it('只有已发布成绩的考试可以归档', () => {
    expect(canArchiveExam('已发布成绩')).toBe(true)
    expect(canArchiveExam('草稿')).toBe(false)
    expect(canArchiveExam('成绩处理中')).toBe(false)
    expect(canArchiveExam('已归档')).toBe(false)
  })

  it('归档后只读提示只在已归档时出现,文案固定', () => {
    expect(archiveReadOnlyHint(archiveFixture)).toBe(ARCHIVE_READONLY_HINT)
    expect(ARCHIVE_READONLY_HINT).toBe('本次考试已归档，归档后只读，成绩与考务数据不再修改。')
    expect(archiveReadOnlyHint(null)).toBe(null)
  })

  it('两次考试无共同科目时原样返回后端 message,有共同科目时不展示', () => {
    const empty: ExamCompare = {
      exam_a: { id: 3, name: '期中考试' }, exam_b: { id: 4, name: '月考' },
      subjects: [], total_avg_a: null, total_avg_b: null, delta_total_avg: null,
      message: '两次考试无共同科目，无法对比',
    }
    expect(compareEmptyMessage(empty)).toBe('两次考试无共同科目，无法对比')
    expect(compareEmptyMessage({ ...empty, message: null }))
      .toBe(COMPARE_NO_COMMON_SUBJECT_MESSAGE)
    const filled: ExamCompare = {
      ...empty,
      subjects: [{
        subject_id: 2, subject_name: '数学', avg_a: 80, avg_b: 85, delta_avg: 5,
        pass_rate_a: 70, pass_rate_b: 75, delta_pass_rate: 5,
        excellent_rate_a: 20, excellent_rate_b: 18, delta_excellent_rate: -2,
      }],
      message: '两次考试无共同科目，无法对比',
    }
    expect(compareEmptyMessage(filled)).toBe(null)
  })

  it('变化值展示:正数带 + 号,负数与零原样,空值显示 —', () => {
    expect(formatDelta(5)).toBe('+5')
    expect(formatDelta(-2)).toBe('-2')
    expect(formatDelta(0)).toBe('0')
    expect(formatDelta(null)).toBe('—')
    expect(formatDelta(undefined)).toBe('—')
  })

  it('备份政策提示沿用清单 KW-67 备注原文', () => {
    expect(BACKUP_POLICY_HINT).toBe('备份频率与存放位置由学校信息安全要求决定。')
  })
})

async function mountArchive() {
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
      { path: '/exam/exams/:id/archive', name: 'exam-exam-archive', component: ExamArchiveView },
    ],
  })
  await router.push('/exam/exams/3/archive')
  await router.isReady()
  const Host = { render: () => h(NMessageProvider, () => h(ExamArchiveView)) }
  const wrapper = mount(Host, { global: { plugins: [pinia, router] } })
  await flushPromises()
  await flushPromises()
  return wrapper
}

describe('归档与备份页分区渲染(KW-65~67)', () => {
  it('未归档时三个分区齐全,展示“尚未归档”与一键归档按钮,不展示只读提示', async () => {
    archiveMode = 'none'
    compareMode = 'empty'
    const wrapper = mountArchive()
    const w = await wrapper
    const text = w.text()
    for (const title of ['考试归档', '历史考试查询与对比', '数据备份与导出']) {
      expect(text).toContain(title)
    }
    expect(text).toContain('期中考试 · 归档与备份')
    expect(w.find('[data-testid="archive-not-archived"]').exists()).toBe(true)
    expect(w.find('[data-testid="archive-not-archived"]').text()).toBe('尚未归档')
    expect(w.find('[data-testid="archive-archive-btn"]').exists()).toBe(true)
    expect(w.find('[data-testid="archive-readonly-hint"]').exists()).toBe(false)
    // 历史列表:两场考试与归档状态
    expect(text).toContain('期中考试')
    expect(text).toContain('月考')
    expect(text).toContain('共 2 场考试')
    // 备份政策提示原文在场
    expect(w.find('[data-testid="archive-backup-policy"]').text())
      .toContain('备份频率与存放位置由学校信息安全要求决定')
    expect(w.find('[data-testid="archive-export-backup"]').exists()).toBe(true)
  })

  it('点一键归档后展示只读提示与 manifest 快照', async () => {
    archiveMode = 'none'
    compareMode = 'empty'
    const w = await mountArchive()
    await w.find('[data-testid="archive-archive-btn"]').trigger('click')
    await flushPromises()
    await flushPromises()
    expect(seenUrls).toContain('/api/exam/exams/3/archive')
    expect(w.find('[data-testid="archive-readonly-hint"]').exists()).toBe(true)
    expect(w.find('[data-testid="archive-readonly-hint"]').text())
      .toBe('本次考试已归档，归档后只读，成绩与考务数据不再修改。')
    expect(w.find('[data-testid="archive-archive-btn"]').exists()).toBe(false)
    const manifest = w.find('[data-testid="archive-manifest"]').text()
    expect(manifest).toContain('参试人数')
    expect(manifest).toContain('120')
    expect(manifest).toContain('总均分')
    expect(w.find('[data-testid="archive-download"]').exists()).toBe(true)
    expect(w.find('[data-testid="archive-unarchive"]').exists()).toBe(true)
  })

  it('已归档进入时直接展示只读提示与 manifest 快照', async () => {
    archiveMode = 'archived'
    compareMode = 'empty'
    const w = await mountArchive()
    expect(w.find('[data-testid="archive-readonly-hint"]').text())
      .toBe('本次考试已归档，归档后只读，成绩与考务数据不再修改。')
    expect(w.find('[data-testid="archive-info"]').text()).toContain('归档时间:2026-11-14 10:00')
    expect(w.find('[data-testid="archive-info"]').text()).toContain('备注:期中归档')
    expect(w.find('[data-testid="archive-manifest-subjects"]').text()).toContain('数学')
    expect(w.find('[data-testid="archive-not-archived"]').exists()).toBe(false)
    archiveMode = 'none'
  })

  it('两次考试无共同科目时原样展示后端 message,有共同科目时展示对比表与变化值', async () => {
    archiveMode = 'none'
    compareMode = 'empty'
    const w = await mountArchive()
    await w.find('[data-testid="archive-set-a-3"]').trigger('click')
    await w.find('[data-testid="archive-set-b-4"]').trigger('click')
    expect(w.find('[data-testid="archive-compare-picked"]').text())
      .toContain('考试 A:期中考试 · 考试 B:月考')
    await w.find('[data-testid="archive-compare-btn"]').trigger('click')
    await flushPromises()
    await flushPromises()
    expect(seenUrls).toContain('/api/exam/archives/compare?exam_a=3&exam_b=4')
    expect(w.find('[data-testid="archive-compare-empty"]').exists()).toBe(true)
    expect(w.find('[data-testid="archive-compare-empty"]').text())
      .toBe('两次考试无共同科目，无法对比')
    expect(w.find('[data-testid="archive-compare-result"]').exists()).toBe(false)

    compareMode = 'filled'
    await w.find('[data-testid="archive-compare-btn"]').trigger('click')
    await flushPromises()
    await flushPromises()
    expect(w.find('[data-testid="archive-compare-empty"]').exists()).toBe(false)
    const result = w.find('[data-testid="archive-compare-result"]')
    expect(result.exists()).toBe(true)
    expect(result.text()).toContain('数学')
    expect(result.text()).toContain('+5')
    expect(result.text()).toContain('-2')
    compareMode = 'empty'
  })
})
