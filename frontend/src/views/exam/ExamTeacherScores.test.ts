import { flushPromises, mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { createPinia, setActivePinia } from 'pinia'
import { h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import ExamTeacherScores from './ExamTeacherScores.vue'
import { useAuthStore } from '@/stores/auth'

vi.stubGlobal('fetch', vi.fn((url: string) => {
  if (url.startsWith('/api/exam/exams/3/teacher-scores')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        items: [{
          student_id: 11, student_no: '202601', student_name: '张三', class_name: '七年二班',
          subject_id: 2, subject_name: '数学', score: 95, status: '正常',
          total: 190, class_rank: 1, grade_rank: 3,
        }],
        total: 1,
      }),
    })
  }
  if (url.startsWith('/api/exam/exams/3/report-settings')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({ exam_id: 3, parent_show_grade_rank: false, parent_show_class_rank: false }),
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

describe('教师端成绩查询页(KW-54)', () => {
  it('查询结果含总分与排名,成绩单设置与成绩册导出入口在场', async () => {
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
        { path: '/exam/exams/:id/teacher-scores', name: 'exam-exam-teacher-scores', component: ExamTeacherScores },
      ],
    })
    await router.push('/exam/exams/3/teacher-scores')
    await router.isReady()
    const Host = { render: () => h(NMessageProvider, () => h(ExamTeacherScores)) }
    const wrapper = mount(Host, { global: { plugins: [pinia, router] } })
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(wrapper.text()).toContain('教师端成绩查询')
    expect(wrapper.text()).toContain('张三')
    expect(wrapper.text()).toContain('共 1 条')
    expect(wrapper.find('[data-testid="teacher-scores-export-grade-book"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="teacher-scores-class-card"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('成绩单设置')
    expect(wrapper.find('[data-testid="report-setting-class-rank"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="report-setting-grade-rank"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="report-setting-save"]').exists()).toBe(true)
  })
})
