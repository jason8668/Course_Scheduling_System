import { flushPromises, mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { createPinia, setActivePinia } from 'pinia'
import { h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import ExamMyScores from './ExamMyScores.vue'
import { useAuthStore } from '@/stores/auth'

let myScoresForbidden = false
vi.stubGlobal('fetch', vi.fn((url: string) => {
  if (url.startsWith('/api/exam/my-report-card')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        student_id: 11, student_no: '202601', student_name: '张三', class_name: '七年二班',
        subjects: [{ subject_id: 2, subject_name: '数学', score: 95, status: '正常' }],
        total: 95, class_rank: 1,
      }),
    })
  }
  if (url.startsWith('/api/exam/my-scores')) {
    if (myScoresForbidden) {
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
  if (url.startsWith('/api/exam/exams')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        items: [{ id: 3, semester_id: 1, name: '期中考试', exam_type: '期中', grades: [7], status: '已发布成绩', description: null, created_at: '2026-11-01' }],
        total: 1,
      }),
    })
  }
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
}))

async function mountMyScores() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.user = {
    id: 9, username: '202601', display_name: '张三', roles: ['student'],
    must_change_password: false,
  }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'dashboard', component: { template: '<div />' } },
      { path: '/exam/my-scores', name: 'exam-my-scores', component: ExamMyScores },
    ],
  })
  await router.push('/exam/my-scores?exam_id=3')
  await router.isReady()
  const Host = { render: () => h(NMessageProvider, () => h(ExamMyScores)) }
  const wrapper = mount(Host, { global: { plugins: [pinia, router] } })
  await flushPromises()
  await flushPromises()
  await flushPromises()
  return wrapper
}

describe('学生/家长自助查询页(KW-55)', () => {
  it('已发布:只显示后端回传的班级排名,缺失的年级排名不显示、不补', async () => {
    myScoresForbidden = false
    const wrapper = mountMyScores()
    const w = await wrapper
    expect(w.text()).toContain('张三')
    expect(w.text()).toContain('班级排名')
    expect(w.text()).not.toContain('年级排名')
    expect(w.find('[data-testid="my-scores-print-btn"]').exists()).toBe(true)
  })

  it('未发布:后端 403 的 detail 原样展示', async () => {
    myScoresForbidden = true
    const w = await mountMyScores()
    const alert = w.find('[data-testid="my-scores-not-published"]')
    expect(alert.exists()).toBe(true)
    expect(alert.text()).toBe('本次考试成绩尚未发布')
  })
})
