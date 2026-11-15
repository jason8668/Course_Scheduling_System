import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import AssetCategories from './AssetCategories.vue'

const SEED = [
  { id: 1, code: 'A01', name: '房屋和构筑物', level: 1, parent_code: null, is_reportable: true, origin: 'gbt14885', is_active: true, sort_order: 0 },
  { id: 2, code: 'A02', name: '设备', level: 1, parent_code: null, is_reportable: true, origin: 'gbt14885', is_active: true, sort_order: 1 },
  { id: 3, code: 'A03', name: '文物和陈列品', level: 1, parent_code: null, is_reportable: true, origin: 'gbt14885', is_active: true, sort_order: 2 },
  { id: 4, code: 'A04', name: '图书和档案', level: 1, parent_code: null, is_reportable: true, origin: 'gbt14885', is_active: true, sort_order: 3 },
  { id: 5, code: 'A05', name: '家具和用具', level: 1, parent_code: null, is_reportable: true, origin: 'gbt14885', is_active: true, sort_order: 4 },
  { id: 6, code: 'A06', name: '特种动植物', level: 1, parent_code: null, is_reportable: true, origin: 'gbt14885', is_active: true, sort_order: 5 },
  { id: 7, code: 'A0201', name: '计算机设备', level: 2, parent_code: 'A02', is_reportable: true, origin: 'seed', is_active: true, sort_order: 6 },
]

let lastUrl = ''
vi.stubGlobal('fetch', vi.fn((url: string) => {
  lastUrl = url
  return Promise.resolve({
    ok: true, status: 200,
    json: () => Promise.resolve(SEED),
  })
}))

describe('资产分类字典页', () => {
  it('展示 GB/T 14885-2022 六大类与上报分类锁定说明', async () => {
    const wrapper = mount(AssetCategories)
    await flushPromises()
    expect(lastUrl).toBe('/api/asset/categories')
    for (const name of ['房屋和构筑物', '设备', '文物和陈列品', '图书和档案', '家具和用具', '特种动植物']) {
      expect(wrapper.text()).toContain(name)
    }
    expect(wrapper.text()).toContain('上报分类代码与名称已锁定')
    expect(wrapper.text()).toContain('是(已锁定)')
    expect(wrapper.text()).toContain('计算机设备')
  })
})
