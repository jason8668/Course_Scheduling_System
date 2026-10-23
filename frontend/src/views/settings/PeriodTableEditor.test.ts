import { flushPromises, mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import PeriodTableEditor from './PeriodTableEditor.vue'

// 模拟后端回传一套 2x2 节次表(周三第2节为固定用途)
const fakeTable = {
  id: 1,
  name: '测试节次表',
  num_weekdays: 3,
  is_default: true,
  periods: [
    { id: 1, weekday: 1, period_no: 1, name: '第一节', start_time: '08:00:00', end_time: '08:40:00', type: 'regular' },
    { id: 2, weekday: 2, period_no: 1, name: '第一节', start_time: '08:00:00', end_time: '08:40:00', type: 'regular' },
    { id: 3, weekday: 3, period_no: 1, name: '第一节', start_time: '08:00:00', end_time: '08:40:00', type: 'regular' },
    { id: 4, weekday: 3, period_no: 2, name: '第二节', start_time: '08:50:00', end_time: '09:30:00', type: 'reserved' },
  ],
}

vi.stubGlobal('fetch', vi.fn(() =>
  Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(fakeTable) }),
))

function makeRouter() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/settings/period-tables/:id', name: 'period-table-editor', component: PeriodTableEditor }],
  })
  router.push('/settings/period-tables/1')
  return router
}

describe('PeriodTableEditor', () => {
  it('载入后渲染节次表名称与周次表头', async () => {
    const router = makeRouter()
    await router.isReady()
    // useMessage 需要 <n-message-provider> 祖先,故以 Host 包裹
    const Host = { render: () => h(NMessageProvider, () => h(PeriodTableEditor)) }
    const wrapper = mount(Host, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('测试节次表')
    expect(wrapper.text()).toContain('周一')
    expect(wrapper.text()).toContain('周三')
    // 固定用途格位应显示
    expect(wrapper.text()).toContain('固定用途')
  })
})
