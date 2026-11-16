import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import AssetDisposal from './AssetDisposal.vue'

vi.stubGlobal('fetch', vi.fn((url: string) => {
  if (url.includes('/disposals/materials')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        disposal_type: 'scrap', label: '报废',
        materials_required: ['技术鉴定单', '资产卡片', '购置凭证'],
      }),
    })
  }
  if (url.includes('/asset/disposals')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve([{
        id: 1, doc_no: 'CZ-20261115-0001', asset_id: 10, disposal_type: 'scrap',
        reason: '示例处置', materials: ['技术鉴定单', '资产卡片', '购置凭证'],
        materials_required: ['技术鉴定单', '资产卡片', '购置凭证'],
        status_before: '在库', status: '待鉴定', approval_instance_id: null,
        selected_for_official: false, official_reply_no: null,
        official_reply_at: null, created_at: '2026-11-15T00:00:00Z',
      }]),
    })
  }
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
}))

describe('处置与报废页', () => {
  it('展示处置单、应交材料与核销前置提示', async () => {
    const wrapper = mount(AssetDisposal)
    await flushPromises()
    expect(wrapper.text()).toContain('处置与报废')
    expect(wrapper.text()).toContain('CZ-20261115-0001')
    expect(wrapper.text()).toContain('技术鉴定单')
    expect(wrapper.text()).toContain('第 5 步回填官方批复文号')
    expect(wrapper.text()).toContain('技术鉴定')
    expect(wrapper.text()).toContain('提交审批')
    expect(wrapper.text()).toContain('生成申报材料包')
    expect(wrapper.text()).toContain('确认核销')
  })
})
