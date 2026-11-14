import { flushPromises, mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { createPinia, setActivePinia } from 'pinia'
import { h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import ExamReportStudent from './ExamReportStudent.vue'
import { useAuthStore } from '@/stores/auth'

vi.stubGlobal('fetch', vi.fn((url: string) => {
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
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
}))

describe('学生个人成绩单页(KW-53)', () => {
  it('未选学生时提示先选学生,打印按钮在场(未出表时置灰)', async () => {
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
        { path: '/exam/exams/:id/report-cards/student', name: 'exam-exam-report-student', component: ExamReportStudent },
      ],
    })
    await router.push('/exam/exams/3/report-cards/student')
    await router.isReady()
    const Host = { render: () => h(NMessageProvider, () => h(ExamReportStudent)) }
    const wrapper = mount(Host, { global: { plugins: [pinia, router] } })
    await flushPromises()
    await flushPromises()
    expect(wrapper.text()).toContain('期中考试 · 个人成绩单')
    expect(wrapper.text()).toContain('请先选择学生')
    const printBtn = wrapper.find('[data-testid="report-student-print-btn"]')
    expect(printBtn.exists()).toBe(true)
    expect(printBtn.attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-testid="report-student-select"]').exists()).toBe(true)
  })
})
