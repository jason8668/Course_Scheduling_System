import { flushPromises, mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { createPinia, setActivePinia } from 'pinia'
import { h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import ExamReportClass from './ExamReportClass.vue'
import { useAuthStore } from '@/stores/auth'

vi.stubGlobal('fetch', vi.fn((url: string) => {
  if (url.startsWith('/api/exam/exams/3')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        id: 3, semester_id: 1, name: '期中考试', exam_type: '期中', grades: [7],
        status: '已发布成绩', description: null, created_at: '2026-11-01',
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
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
}))

describe('班级成绩单打印页(KW-52)', () => {
  it('未选班级时提示先选班级,打印按钮在场(未出表时置灰)', async () => {
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
        { path: '/exam/exams/:id/report-cards/class', name: 'exam-exam-report-class', component: ExamReportClass },
      ],
    })
    await router.push('/exam/exams/3/report-cards/class')
    await router.isReady()
    const Host = { render: () => h(NMessageProvider, () => h(ExamReportClass)) }
    const wrapper = mount(Host, { global: { plugins: [pinia, router] } })
    await flushPromises()
    await flushPromises()
    expect(wrapper.text()).toContain('期中考试 · 班级成绩单')
    expect(wrapper.text()).toContain('请先选择班级')
    const printBtn = wrapper.find('[data-testid="report-class-print-btn"]')
    expect(printBtn.exists()).toBe(true)
    expect(printBtn.attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-testid="report-class-select"]').exists()).toBe(true)
  })
})
