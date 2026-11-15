import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import AssetSyncPool from './AssetSyncPool.vue'

vi.stubGlobal('fetch', vi.fn((url: string) => {
  if (url.includes('/sync/pool')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        items: [{
          asset_id: 1, asset_code: 'ZC2026A02030001', name: '示例资产',
          category_code: 'A0203', manage_dept: '教务处', original_value: 3000,
          sync_status: '待同步', selected_by: 2, selected_at: '2026-11-15T00:00:00Z',
          selection_batch_no: 'GX20261115-0001',
        }],
        total: 1, total_value: 3000,
        groups: { 'GX20261115-0001': { count: 1, total_value: 3000 } },
      }),
    })
  }
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
}))

describe('待同步池页', () => {
  it('展示清单、件数、总价值与按批次分组', async () => {
    const wrapper = mount(AssetSyncPool)
    await flushPromises()
    expect(wrapper.text()).toContain('待同步池')
    expect(wrapper.text()).toContain('共 1 件,总价值 3000 元')
    expect(wrapper.text()).toContain('GX20261115-0001')
    expect(wrapper.text()).toContain('示例资产')
    expect(wrapper.text()).toContain('取消勾选')
  })
})
