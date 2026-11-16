import { NSelect } from 'naive-ui'
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import AssetPicker from './AssetPicker.vue'

const CARD = {
  id: 1, asset_code: 'ZC2026A02030001', official_code: null,
  label_code: 'ZC2026A02030001X', name: '示例打印机', category_code: 'A0203',
  spec_model: null, unit: '件', acquired_date: null, acquire_method: 'purchase',
  source: null, supplier: null, original_value: 2500, funding_source: 'fiscal',
  voucher_no: null, status: '在库', manage_dept: '教务处', use_dept: null,
  custodian_name: '示例保管人', campus: null, building: null, room_name: null,
  borrow_status: '未领用', attributes: null, ext: null, sync_status: '未同步',
  is_retired: false, batch_no: null, acceptance_id: null, is_booked: false,
  booked_at: null, last_used_at: null, is_idle: false, idle_reason: null,
  created_at: null,
}

const fetchMock = vi.fn((url: string) => {
  if (url.includes('/ledger/search')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({ items: [CARD], total: 1 }),
    })
  }
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
})
vi.stubGlobal('fetch', fetchMock)

describe('资产选择器', () => {
  it('占位提示写明按编号或名称搜索，不再让用户填内部 id', () => {
    const wrapper = mount(AssetPicker, { props: { modelValue: null } })
    expect(wrapper.text()).toContain('输入资产编号或名称搜索')
  })

  it('输入关键词后调台账组合查询并给出“编号 + 名称”候选项', async () => {
    const wrapper = mount(AssetPicker, { props: { modelValue: null } })
    // 用 $emit 驱动内层 n-select,不真实展开下拉(测试环境无 matchMedia)。
    const sel = wrapper.findComponent(NSelect)
    await sel.vm.$emit('search', '打印机')
    await flushPromises()
    expect(fetchMock).toHaveBeenCalled()
    const called = fetchMock.mock.calls.some((c) => String(c[0]).includes('q=%E6%89%93%E5%8D%B0%E6%9C%BA')
      || String(c[0]).includes('q=打印机'))
    expect(called).toBe(true)
    await sel.vm.$emit('update:value', 1)
    await flushPromises()
    const emitted = wrapper.emitted('select')
    expect(emitted?.[0]?.[0]).toMatchObject({ asset_code: 'ZC2026A02030001', name: '示例打印机' })
  })
})
