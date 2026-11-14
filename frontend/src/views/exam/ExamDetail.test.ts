import { flushPromises, mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { createPinia, setActivePinia } from 'pinia'
import { h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import ExamDetail from './ExamDetail.vue'
import { useAuthStore } from '@/stores/auth'

function stubFetchFor(status: string) {
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    if (url.startsWith('/api/exam/exams/3/participants')) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ items: [], total: 0 }) })
    }
    if (url.startsWith('/api/exam/exams/3/paper-info')) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ items: [] }) })
    }
    if (url.startsWith('/api/exam/exams/3/special-arrangements')) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ items: [] }) })
    }
    if (url.startsWith('/api/exam/exams/3')) {
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve({
          id: 3, semester_id: 1, name: '期中考试', exam_type: '期中', grades: [7],
          status, description: null, created_at: '2026-11-01', subjects: [], participant_count: 0,
        }),
      })
    }
    if (url.startsWith('/api/exam/students')) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ items: [], total: 0 }) })
    }
    if (url.startsWith('/api/subjects') || url.startsWith('/api/teachers') || url.startsWith('/api/class-units')) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) })
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
  }))
}

async function makeRouter() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/exam/exams', name: 'exam-exams', component: { template: '<div />' } },
      { path: '/exam/exams/:id', name: 'exam-exam-detail', component: ExamDetail },
    ],
  })
  await router.push('/exam/exams/3')
  await router.isReady()
  return router
}

async function mountDetail(status: string) {
  stubFetchFor(status)
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.user = {
    id: 1, username: 'admin', display_name: '系统管理员', roles: ['admin'],
    must_change_password: false,
  }
  const Host = { render: () => h(NMessageProvider, () => h(ExamDetail)) }
  const wrapper = mount(Host, { global: { plugins: [pinia, await makeRouter()] } })
  await flushPromises()
  await flushPromises()
  return wrapper
}

describe('考试详情页状态流转', () => {
  it('草稿状态:当前状态高亮,推进按钮指向已发布,回退按钮可见', async () => {
    const wrapper = await mountDetail('草稿')
    expect(wrapper.text()).toContain('期中考试')
    const current = wrapper.find('[data-testid="exam-current-status"]')
    expect(current.exists()).toBe(true)
    expect(current.text()).toBe('草稿')
    const advance = wrapper.find('[data-testid="exam-advance"]')
    expect(advance.exists()).toBe(true)
    expect(advance.text()).toContain('推进到已发布')
    expect(wrapper.find('[data-testid="exam-backward"]').exists()).toBe(false)
  })

  it('进行中状态:推进按钮指向成绩处理中,回退按钮可见', async () => {
    const wrapper = await mountDetail('进行中')
    const advance = wrapper.find('[data-testid="exam-advance"]')
    expect(advance.exists()).toBe(true)
    expect(advance.text()).toContain('推进到成绩处理中')
    expect(wrapper.find('[data-testid="exam-backward"]').exists()).toBe(true)
  })

  it('已归档状态:没有推进按钮,显示流转结束', async () => {
    const wrapper = await mountDetail('已归档')
    expect(wrapper.find('[data-testid="exam-advance"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('已归档,状态流转已结束')
  })

  it('特殊考生安排区有仅教务与监考可见的隐私提示', async () => {
    const wrapper = await mountDetail('草稿')
    const tip = wrapper.find('[data-testid="special-arrangement-privacy"]')
    expect(tip.exists()).toBe(true)
    expect(tip.text()).toContain('仅教务与相关监考教师可见')
  })
})
