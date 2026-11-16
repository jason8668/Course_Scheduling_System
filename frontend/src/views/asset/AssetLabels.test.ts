import { NSelect } from 'naive-ui'
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import AssetLabels from './AssetLabels.vue'

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
const LABEL = {
  asset_id: 1, asset_code: 'ZC2026A02030001', label_code: 'ZC2026A02030001X',
  name: '示例资产', manage_dept: '教务处', valid: true,
}

vi.stubGlobal('fetch', vi.fn((url: string) => {
  if (url.includes('/ledger/search')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({ items: [CARD], total: 1 }),
    })
  }
  if (url.includes('/ledger/labels')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve([LABEL]),
    })
  }
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
}))

describe('标签打印页', () => {
  it('空清单时给搜索引导,不再让用户手填内部 id', async () => {
    const wrapper = mount(AssetLabels)
    await flushPromises()
    expect(wrapper.text()).toContain('二维码标签打印')
    expect(wrapper.text()).toContain('加入打印清单')
    expect(wrapper.text()).toContain('加载标签')
    expect(wrapper.text()).toContain('批量打印')
    expect(wrapper.text()).toContain('还没有加入任何资产')
    expect(wrapper.text()).not.toContain('资产 id')
  })

  it('搜索加入清单后加载标签,每张标签含二维码图', async () => {
    const wrapper = mount(AssetLabels)
    await flushPromises()
    // 用 $emit 驱动选择器里的 n-select 搜索并选中,不真实展开下拉(测试环境无 matchMedia)。
    const sel = wrapper.findComponent(NSelect)
    await sel.vm.$emit('search', '示例')
    await flushPromises()
    await sel.vm.$emit('update:value', 1)
    await flushPromises()
    const buttons = wrapper.findAll('button')
    const addBtn = buttons.find((b) => b.text() === '加入打印清单')
    expect(addBtn?.attributes('disabled')).toBeUndefined()
    await addBtn!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('ZC2026A02030001')
    const loadBtn = wrapper.findAll('button').find((b) => b.text() === '加载标签')
    await loadBtn!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('示例资产')
    expect(wrapper.text()).toContain('教务处')
    const img = wrapper.find('img[alt="二维码"]')
    expect(img.exists()).toBe(true)
    expect(img.attributes('src')).toContain('/api/asset/assets/1/label/qr')
  })
})
