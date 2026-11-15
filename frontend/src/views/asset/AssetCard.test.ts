import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import AssetCard from './AssetCard.vue'

const CARD = {
  id: 1, asset_code: 'ZC2026A02030001', official_code: null,
  label_code: 'ZC2026A02030001X', name: '示例资产', category_code: 'A0203',
  spec_model: '示例型号', unit: '件', acquired_date: null, acquire_method: 'purchase',
  source: '示例来源', supplier: null, original_value: 2500, funding_source: 'fiscal',
  voucher_no: null, status: '在库', manage_dept: '教务处', use_dept: null,
  custodian_name: '示例保管人', campus: '示例校区', building: '示例楼',
  room_name: '示例房间', borrow_status: '未领用',
  attributes: { precision_grade: '一级' }, ext: { remark: '演示备注' },
  sync_status: '未同步', is_retired: false, batch_no: 'RK20261115-0001',
  acceptance_id: 1, is_booked: false, booked_at: null, last_used_at: null,
  is_idle: false, idle_reason: null, created_at: null,
}

vi.stubGlobal('fetch', vi.fn((url: string) => {
  if (url.includes('/attachments')) {
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) })
  }
  if (url.includes('/timeline')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve([
        {
          time: '2026-11-15T08:00:00Z', type: '建卡',
          title: '建卡 ZC2026A02030001', detail: '示例资产 分类A0203',
          doc_no: null, actor: '',
        },
        {
          time: '2026-11-15T09:00:00Z', type: '审计',
          title: 'asset_card_create', detail: '建卡 ZC2026A02030001 示例资产',
          doc_no: null, actor: '示例管理员',
        },
      ]),
    })
  }
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(CARD) })
}))

describe('资产卡页', () => {
  it('展示四区 + 扩展区 + 附件 + 勾选同步按钮', async () => {
    const wrapper = mount(AssetCard, { props: { assetId: 1 } })
    await flushPromises()
    expect(wrapper.text()).toContain('资产卡')
    expect(wrapper.text()).toContain('基本信息区')
    expect(wrapper.text()).toContain('财务信息区')
    expect(wrapper.text()).toContain('使用信息区')
    expect(wrapper.text()).toContain('特性信息区')
    expect(wrapper.text()).toContain('校内扩展区')
    expect(wrapper.text()).toContain('ZC2026A02030001')
    expect(wrapper.text()).toContain('附件与影像归档')
    expect(wrapper.text()).toContain('勾选同步')
    expect(wrapper.text()).toContain('补打标签')
    expect(wrapper.text()).toContain('履历时间轴')
    expect(wrapper.text()).toContain('建卡 ZC2026A02030001')
    expect(wrapper.text()).toContain('asset_card_create')
  })
})
