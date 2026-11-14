import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import Portal from './Portal.vue'

function makeRouter() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'portal', component: Portal },
      { path: '/scheduling-center', name: 'scheduling-center', component: { template: '<div />' } },
      { path: '/exam/students', name: 'exam-students', component: { template: '<div />' } },
    ],
  })
  return router
}

describe('Portal', () => {
  it('只排两个已建成系统的入口卡,标题与副标题正确', async () => {
    const router = makeRouter()
    await router.push('/')
    await router.isReady()
    const wrapper = mount(Portal, {
      global: { plugins: [router] },
    })
    expect(wrapper.text()).toContain('智慧教务系统')
    expect(wrapper.text()).toContain('一个账号，进各个系统')
    expect(wrapper.find('[data-testid="entry-scheduling"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="entry-scheduling"]').text()).toContain('排课系统')
    expect(wrapper.find('[data-testid="entry-exam"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="entry-exam"]').text()).toContain('考务成绩系统')
    // 没建成的系统不画占位卡片:入口卡正好两张
    expect(wrapper.findAll('.entry-card').length).toBe(2)
  })

  it('点排课卡进排课中心,点考务卡进学生档案', async () => {
    const router = makeRouter()
    await router.push('/')
    await router.isReady()
    const wrapper = mount(Portal, {
      global: { plugins: [router] },
    })
    await wrapper.find('[data-testid="entry-scheduling"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('scheduling-center')
    await router.push('/')
    await wrapper.find('[data-testid="entry-exam"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('exam-students')
  })
})
