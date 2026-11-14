import { flushPromises, mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { createPinia, setActivePinia } from 'pinia'
import { h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import Exams from './Exams.vue'
import { useAuthStore } from '@/stores/auth'

vi.stubGlobal('fetch', vi.fn((url: string) => {
  if (url.startsWith('/api/semesters')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve([{ id: 1, academic_year: 2026, term: 1, label: '2026 学年第一学期', status: 'active', start_date: null, end_date: null }]),
    })
  }
  if (url.startsWith('/api/class-units')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve([
        { id: 5, semester_id: 1, grade: 7, name: '七年一班', track: 'junior_high', department: null, student_count: null, homeroom_teacher_id: null, homeroom_teacher: null, period_table_id: null },
      ]),
    })
  }
  if (url.startsWith('/api/exam/exams')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        items: [{ id: 3, semester_id: 1, name: '期中考试', exam_type: '期中', grades: [7], status: '草稿', description: null, created_at: '2026-11-01' }],
        total: 1,
      }),
    })
  }
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
}))

function makeRouter() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/exam/exams', name: 'exam-exams', component: Exams },
      { path: '/exam/exams/:id', name: 'exam-exam-detail', component: { template: '<div />' } },
    ],
  })
  void router.push('/exam/exams')
  return router
}

describe('考试列表页', () => {
  it('按学期/状态/名称检索入口都在,列表显示考试并能点进详情', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    auth.user = {
      id: 1, username: 'admin', display_name: '系统管理员', roles: ['admin'],
      must_change_password: false,
    }
    const Host = { render: () => h(NMessageProvider, () => h(Exams)) }
    const wrapper = mount(Host, { global: { plugins: [pinia, makeRouter()] } })
    await flushPromises()
    expect(wrapper.text()).toContain('考试管理')
    expect(wrapper.text()).toContain('期中考试')
    expect(wrapper.text()).toContain('草稿')
    expect(wrapper.text()).toContain('共 1 场考试')
    const buttons = wrapper.findAll('button')
    expect(buttons.find((b) => b.text().includes('新建考试'))).toBeTruthy()
    expect(buttons.find((b) => b.text().includes('检索'))).toBeTruthy()
    // 列表行点考试名称进详情:路由跳到 /exam/exams/3
    const nameBtn = buttons.find((b) => b.text() === '期中考试')
    expect(nameBtn).toBeTruthy()
    await nameBtn!.trigger('click')
    await flushPromises()
    expect(wrapper.vm.$router.currentRoute.value.name).toBe('exam-exam-detail')
  })
})
