import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import AssetRepair from './AssetRepair.vue'

vi.stubGlobal('fetch', vi.fn((url: string) => {
  if (url.includes('/repairs/scan')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        asset_id: 1, asset_code: 'ZC2026A020001', name: '示例资产', status: '在库',
        room_name: '示例机房', custodian_name: '示例保管人',
        warranty_until: '2030-06-01', in_warranty: true,
        warranty_hint: '保内故障,请走厂商保修(保修至 2030-06-01)',
        repair_order_id: 1, doc_no: 'WX-20261115-0001', created: true,
      }),
    })
  }
  if (url.includes('/repairs/summary')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        asset_id: 1, total_cost: 800, closed_count: 1, open_count: 0, threshold: 5000,
      }),
    })
  }
  if (url.includes('/repairs')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve([{
        id: 1, doc_no: 'WX-20261115-0001', asset_id: 1, source: '报修',
        source_doc_no: null, reporter_id: 7, reporter_name: '示例保管人',
        description: '示例故障:无法开机', status: '待确认', photo_url: null,
        assignee_id: null, assignee_name: '示例维修员', vendor: '示例厂商',
        cost: 800, result: '示例维修:更换电源', pre_repair_status: '在库',
        approval_instance_id: null, confirmed_by: null, confirmed_at: null,
        closed_at: null, created_at: '2026-11-15T00:00:00Z',
      }]),
    })
  }
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
}))

describe('维修与保养页', () => {
  it('展示扫码报修保内提示、工单列表与报修人确认入口、费用累计', async () => {
    const wrapper = mount(AssetRepair)
    await flushPromises()
    expect(wrapper.text()).toContain('维修与保养')
    expect(wrapper.text()).toContain('扫码报修')
    expect(wrapper.text()).toContain('WX-20261115-0001')
    expect(wrapper.text()).toContain('报修人确认关闭 WX-20261115-0001')
    expect(wrapper.text()).toContain('派单 / 送修')
    expect(wrapper.text()).toContain('登记维修方、费用、结果')
    expect(wrapper.text()).toContain('维修费用累计')
    // 点击一键报修:保内提示走厂商保修
    const buttons = wrapper.findAll('button')
    const reportBtn = buttons.find((b) => b.text() === '一键报修')
    expect(reportBtn).toBeTruthy()
    await reportBtn!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('保内故障,请走厂商保修')
  })
})
