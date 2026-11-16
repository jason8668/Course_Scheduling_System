import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import AssetWorkspace from './AssetWorkspace.vue'

async function mountWorkspace() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/asset/workspace', name: 'asset-workspace', component: AssetWorkspace },
      { path: '/asset/intake', name: 'asset-intake', component: { template: '<div />' } },
      { path: '/asset/ledger', name: 'asset-ledger', component: { template: '<div />' } },
      { path: '/asset/circulation', name: 'asset-circulation', component: { template: '<div />' } },
      { path: '/asset/transfer', name: 'asset-transfer', component: { template: '<div />' } },
      { path: '/asset/sync-pool', name: 'asset-sync-pool', component: { template: '<div />' } },
    ],
  })
  await router.push({ name: 'asset-workspace' })
  await router.isReady()
  const wrapper = mount(AssetWorkspace, { global: { plugins: [router] } })
  return { wrapper, router }
}

vi.stubGlobal('fetch', vi.fn((url: string) => {
  if (url.includes('/workspace/todos')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve([
        {
          kind: '借用逾期', title: '借用已逾期 2 天:ZC2026A02030001',
          detail: '借用单 JY-20261115-0001', target_type: 'borrow_order',
          target_id: 2, due_at: '2026-11-13T17:00:00Z', urgency: '逾期', urgency_rank: 0,
        },
        {
          kind: '待审批', title: '待审批:领用单#LY-20261115-0001',
          detail: '当前节点:asset_dept_admin', target_type: 'approval_instance',
          target_id: 1, due_at: '2026-11-18T00:00:00Z', urgency: '待审批', urgency_rank: 2,
        },
      ]),
    })
  }
  if (url.includes('/workspace/my-assets')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        items: [{
          id: 1, asset_code: 'ZC2026A02030001', name: '示例资产', status: '在用',
          custodian_name: '示例保管人',
        }],
        total: 1,
      }),
    })
  }
  if (url.includes('/workspace/reminders')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve([{
        id: 1, kind: '借用逾期', user_id: 7, target_type: 'borrow_order',
        target_id: 2, title: '借用已逾期 2 天:ZC2026A02030001', content: '请尽快归还',
        level: '逾期', is_read: false, is_dingtalk_sent: false,
        created_at: '2026-11-15T00:00:00Z',
      }]),
    })
  }
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
}))

describe('我的工作台页', () => {
  it('展示待办(逾期在前)、我的资产与报修归还入口、提醒中心', async () => {
    const { wrapper } = await mountWorkspace()
    await flushPromises()
    expect(wrapper.text()).toContain('我的工作台')
    expect(wrapper.text()).toContain('我的待办')
    expect(wrapper.text()).toContain('借用已逾期 2 天')
    expect(wrapper.text()).toContain('待审批:领用单')
    expect(wrapper.text()).toContain('我的资产')
    expect(wrapper.text()).toContain('ZC2026A02030001')
    expect(wrapper.text()).toContain('报修 ZC2026A02030001')
    expect(wrapper.text()).toContain('归还 ZC2026A02030001')
    expect(wrapper.text()).toContain('消息与提醒中心')
    expect(wrapper.text()).toContain('未读')
  })
})
