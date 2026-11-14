import { flushPromises, mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { createPinia, setActivePinia } from 'pinia'
import { h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import ExamAccounts from './ExamAccounts.vue'
import { useAuthStore } from '@/stores/auth'

vi.stubGlobal('fetch', vi.fn((url: string) => {
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
  if (url.startsWith('/api/exam/accounts')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        items: [{ user_id: 7, username: '202601', role: 'student', student_names: ['张三'], must_change_password: true }],
        total: 1,
      }),
    })
  }
  if (url.startsWith('/api/semesters')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve([
        { id: 1, academic_year: 2026, term: 1, label: '2026-2027 学年第一学期', status: 'active' },
      ]),
    })
  }
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
}))

async function mountAccounts() {
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
      { path: '/exam/accounts', name: 'exam-exam-accounts', component: ExamAccounts },
    ],
  })
  await router.push('/exam/accounts')
  await router.isReady()
  const Host = { render: () => h(NMessageProvider, () => h(ExamAccounts)) }
  const wrapper = mount(Host, {
    attachTo: document.body,
    global: { plugins: [pinia, router] },
  })
  await flushPromises()
  await flushPromises()
  return wrapper
}

describe('学生/家长账号开通管理页(KW-55)', () => {
  it('账号清单展示用户名与关联学生;一键开通后醒目提示口令只显示一次并列出初始口令', async () => {
    const wrapper = await mountAccounts()
    try {
      expect(wrapper.text()).toContain('202601')
      expect(wrapper.find('[data-testid="accounts-provision-btn"]').exists()).toBe(true)
      // 点一键开通:先点触发按钮弹出二次确认,再点确认开通(NModal 内容 teleport 到 body)
      await wrapper.find('[data-testid="accounts-provision-btn"]').trigger('click')
      await flushPromises()
      const confirmEl = document.body.querySelector('[data-testid="accounts-provision-confirm"]') as HTMLElement | null
      expect(confirmEl).not.toBeNull()
      confirmEl!.click()
      await flushPromises()
      await flushPromises()
      await flushPromises()
      const hint = wrapper.find('[data-testid="accounts-once-hint"]')
      expect(hint.exists()).toBe(true)
      expect(hint.text()).toContain('口令只显示一次，请立即分发，关闭后无法再次查看')
      expect(wrapper.text()).toContain('Ab12345678')
      expect(wrapper.text()).toContain('13812345678')
      expect(wrapper.find('[data-testid="accounts-export-csv"]').exists()).toBe(true)
    } finally {
      wrapper.unmount()
    }
  })
})
