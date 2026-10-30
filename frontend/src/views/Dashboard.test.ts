import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import Dashboard from './Dashboard.vue'
import { useAuthStore } from '@/stores/auth'

// 无学期时 listSemesters 回空阵列 → 显示空状态
vi.stubGlobal('fetch', vi.fn(() =>
  Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) }),
))

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'dashboard', component: Dashboard },
      { path: '/wizard', name: 'wizard', component: { template: '<div />' } },
    ],
  })
}

describe('Dashboard', () => {
  it('无学期时显示空状态与前往精灵', async () => {
    // 向导空状态只给管理员看(教师看不到学期列表,给教师看向导是错的),
    // 故测试里先把登录身份设为管理员。
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    auth.user = {
      id: 1, username: 'admin', display_name: '系统管理员', roles: ['admin'],
      must_change_password: false,
    }
    const wrapper = mount(Dashboard, {
      global: { plugins: [pinia, makeRouter()] },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('仪表板')
    expect(wrapper.text()).toContain('尚未建立任何学期资料')
  })
})
