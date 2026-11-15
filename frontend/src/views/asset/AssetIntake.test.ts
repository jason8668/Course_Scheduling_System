import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import AssetIntake from './AssetIntake.vue'

vi.stubGlobal('fetch', vi.fn((url: string) => {
  if (url.includes('/acceptances')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve([{
        id: 1, acceptance_no: 'YS20261115-0001', intake_type: 'gov_purchase',
        status: '待验收', source_doc: { contract_no: '示例合同-1' },
        acceptors: ['示例验收人'], accepted_by: null, accepted_at: null,
        comment: '', batch_no: null, created_at: null,
      }]),
    })
  }
  if (url.includes('/booking-pending')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({ items: [], total: 0, total_value: 0 }),
    })
  }
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
}))

describe('入库验收页', () => {
  it('展示验收单列表与待入账清单', async () => {
    const wrapper = mount(AssetIntake)
    await flushPromises()
    expect(wrapper.text()).toContain('入库验收')
    expect(wrapper.text()).toContain('新建验收单')
    expect(wrapper.text()).toContain('验收单列表')
    expect(wrapper.text()).toContain('YS20261115-0001')
    expect(wrapper.text()).toContain('待入账清单')
    expect(wrapper.text()).toContain('验收不通过的资产不得建卡')
  })
})
