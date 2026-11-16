import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import AssetList from './AssetList.vue'

async function mountList() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/asset/ledger', name: 'asset-ledger', component: AssetList },
      { path: '/asset/cards', name: 'asset-card', component: { template: '<div />' } },
      { path: '/asset/intake', name: 'asset-intake', component: { template: '<div />' } },
    ],
  })
  await router.push({ name: 'asset-ledger' })
  await router.isReady()
  const wrapper = mount(AssetList, { global: { plugins: [router] } })
  return { wrapper, router }
}

const CARD = {
  id: 1, asset_code: 'ZC2026A02030001', official_code: null,
  label_code: 'ZC2026A02030001X', name: '示例资产', category_code: 'A0203',
  spec_model: null, unit: '件', acquired_date: null, acquire_method: 'purchase',
  source: null, supplier: null, original_value: 2500, funding_source: 'fiscal',
  voucher_no: null, status: '在库', manage_dept: '教务处', use_dept: null,
  custodian_name: '示例保管人', campus: null, building: null, room_name: null,
  borrow_status: '未领用', attributes: null, ext: null, sync_status: '未同步',
  is_retired: false, batch_no: null, acceptance_id: null, is_booked: false,
  booked_at: null, last_used_at: null, is_idle: false, idle_reason: null,
  created_at: null,
}

vi.stubGlobal('fetch', vi.fn((url: string) => {
  if (url.includes('/ledger/search')) {
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ items: [CARD], total: 1 }) })
  }
  if (url.includes('/idle')) {
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) })
  }
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
}))

describe('资产台账页', () => {
  it('展示组合查询结果与闲置清单入口', async () => {
    const { wrapper } = await mountList()
    await flushPromises()
    expect(wrapper.text()).toContain('资产台账')
    expect(wrapper.text()).toContain('示例资产')
    expect(wrapper.text()).toContain('ZC2026A02030001')
    expect(wrapper.text()).toContain('导出 Excel')
    expect(wrapper.text()).toContain('勾选同步')
    expect(wrapper.text()).toContain('闲置清单')
    expect(wrapper.text()).toContain('共 1 件')
  })

  it('点资产编号进资产卡页', async () => {
    const { wrapper, router } = await mountList()
    await flushPromises()
    const codeBtn = wrapper.findAll('button').find((b) => b.text() === 'ZC2026A02030001')
    expect(codeBtn?.exists()).toBe(true)
    await codeBtn!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('asset-card')
    expect(router.currentRoute.value.query.id).toBe('1')
  })
})
