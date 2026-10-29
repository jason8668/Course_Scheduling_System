import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import Dashboard from './Dashboard.vue'

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
    const wrapper = mount(Dashboard, {
      global: { plugins: [createPinia(), makeRouter()] },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('首页')
    expect(wrapper.text()).toContain('尚未建立任何学期资料')
  })
})
