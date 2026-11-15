import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import AssetLabels from './AssetLabels.vue'

vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
  ok: true, status: 200,
  json: () => Promise.resolve([{
    asset_id: 1, asset_code: 'ZC2026A02030001', label_code: 'ZC2026A02030001X',
    name: '示例资产', manage_dept: '教务处', valid: true,
  }]),
})))

describe('标签打印页', () => {
  it('展示标签加载入口与打印说明', async () => {
    const wrapper = mount(AssetLabels)
    await flushPromises()
    expect(wrapper.text()).toContain('二维码标签打印')
    expect(wrapper.text()).toContain('加载标签')
    expect(wrapper.text()).toContain('批量打印')
    expect(wrapper.text()).toContain('请先输入资产 id 加载标签')
  })

  it('加载标签后展示名称、编号与保管部门', async () => {
    const wrapper = mount(AssetLabels)
    const input = wrapper.find('input')
    await input.setValue('1')
    const buttons = wrapper.findAll('button')
    await buttons[0].trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('示例资产')
    expect(wrapper.text()).toContain('ZC2026A02030001')
    expect(wrapper.text()).toContain('教务处')
  })

  it('#28 复核补:每张标签含二维码图,src 指向后端 QR 端点', async () => {
    const wrapper = mount(AssetLabels)
    const input = wrapper.find('input')
    await input.setValue('1')
    const buttons = wrapper.findAll('button')
    await buttons[0].trigger('click')
    await flushPromises()
    const img = wrapper.find('img[alt="二维码"]')
    expect(img.exists()).toBe(true)
    expect(img.attributes('src')).toContain('/api/asset/assets/1/label/qr')
  })
})
