import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import AssetInventory from './AssetInventory.vue'

vi.stubGlobal('fetch', vi.fn((url: string) => {
  if (url.includes('/differences')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve([{
        id: 1, plan_id: 1, task_id: 1, asset_id: 2, asset_code: 'ZC2026A020002',
        asset_name: '示例盘亏资产', diff_type: '盘亏', status: '待处理',
        detail: '台账有、实盘无', resolution: '', involves_synced: false,
        acceptance_id: null, created_at: '2026-11-15T00:00:00Z',
      }, {
        id: 2, plan_id: 1, task_id: 1, asset_id: null, asset_code: null,
        asset_name: '示例未贴标资产', diff_type: '盘盈', status: '待处理',
        detail: '实盘有、台账无', resolution: '', involves_synced: false,
        acceptance_id: null, created_at: '2026-11-15T00:00:00Z',
      }]),
    })
  }
  if (url.includes('/compute-diffs')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        task_id: 1, counts: { '正常': 1, '盘亏': 1, '盘盈': 1, '位置不符': 1, '保管人不符': 1 },
      }),
    })
  }
  if (url.includes('/inventory/plans')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve([{
        id: 1, plan_no: 'PD-20261115-0001', name: '示例盘点方案',
        plan_type: '全校盘点', note: '', status: '进行中',
        created_at: '2026-11-15T00:00:00Z',
      }]),
    })
  }
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
}))

describe('盘点清查页', () => {
  it('展示盘点方案、扫码盘点、五类差异清单与关闭入口', async () => {
    const wrapper = mount(AssetInventory)
    await flushPromises()
    expect(wrapper.text()).toContain('盘点清查')
    expect(wrapper.text()).toContain('盘点方案与任务拆分')
    expect(wrapper.text()).toContain('PD-20261115-0001')
    expect(wrapper.text()).toContain('手机扫码盘点')
    expect(wrapper.text()).toContain('未贴标资产现场补录拍照')
    expect(wrapper.text()).toContain('五类差异清单与处理')
    expect(wrapper.text()).toContain('领导确认关闭盘点')
    // 点击五类差异自动比对:加载差异清单
    const buttons = wrapper.findAll('button')
    const diffBtn = buttons.find((b) => b.text() === '五类差异自动比对')
    expect(diffBtn).toBeTruthy()
    await diffBtn!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('盘亏')
    expect(wrapper.text()).toContain('盘盈')
    expect(wrapper.text()).toContain('示例未贴标资产')
  })
})
