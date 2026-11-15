import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import AssetMobile from './AssetMobile.vue'

// 移动端四件事(#113)只复用已有接口:查卡=台账查询 q、报修=扫码报修、
// 确认=领用扫码确认、盘点=手机扫码盘点;按 URL 分流 stub fetch。
vi.stubGlobal('fetch', vi.fn((url: string) => {
  const u = String(url)
  if (u.includes('/asset/ledger/search')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        items: [{
          id: 1, asset_code: 'ZC2026A02030001', official_code: null,
          label_code: 'ZC2026A02030001X', name: '示例资产', category_code: 'A0203',
          spec_model: null, unit: '台', acquired_date: null, acquire_method: '购置',
          source: null, supplier: null, original_value: 12000, funding_source: null,
          voucher_no: null, status: '在库', manage_dept: '教务处', use_dept: null,
          custodian_name: '示例保管人', campus: null, building: null, room_name: '示例教室',
          borrow_status: '可借', attributes: null, ext: null,
        }],
        total: 1,
      }),
    })
  }
  if (u.includes('/asset/repairs/scan')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        asset_id: 1, asset_code: 'ZC2026A02030001', name: '示例资产', status: '在库',
        room_name: '示例教室', custodian_name: '示例保管人',
        warranty_until: '2027-01-01', in_warranty: true,
        warranty_hint: '保内,请走厂商保修', repair_order_id: 7, doc_no: 'WX-示例',
        created: true,
      }),
    })
  }
  if (u.includes('/asset/issues/') && u.includes('/confirm-scan')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        id: 3, doc_no: 'LY-示例', asset_id: 1, applicant_id: 2,
        applicant_name: '示例申请人', use_dept: null, reason: '教学使用',
        status: '已确认', approval_instance_id: null, issued_by: null,
        issued_at: null, confirmed_at: '2026-11-15T00:00:00Z', created_at: null,
      }),
    })
  }
  if (u.includes('/asset/inventory/tasks/') && u.includes('/scan')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        in_scope: true, message: '盘点记录成功', record_id: 9,
        asset_id: 1, asset_code: 'ZC2026A02030001',
      }),
    })
  }
  return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({ detail: '未找到' }) })
}))

async function clickTab(wrapper: ReturnType<typeof mount>, index: number) {
  const buttons = wrapper.findAll('button')
  // 前 4 个大按钮即四件事入口。
  await buttons[index].trigger('click')
  await flushPromises()
}

describe('移动端四件事页', () => {
  it('只列四件事入口与手机端范围说明', () => {
    const wrapper = mount(AssetMobile)
    const text = wrapper.text()
    expect(text).toContain('扫码查卡')
    expect(text).toContain('扫码报修')
    expect(text).toContain('借用/领用确认')
    expect(text).toContain('盘点作业')
    expect(text).toContain('手机端只做四件事')
    expect(text).toContain('同步执行、审批、处置等请在电脑端办理')
  })

  it('扫码查卡:输入编号后展示资产卡关键字段', async () => {
    const wrapper = mount(AssetMobile)
    await wrapper.find('input').setValue('ZC2026A02030001')
    const buttons = wrapper.findAll('button')
    await buttons.find((b) => b.text() === '查卡')!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('示例资产')
    expect(wrapper.text()).toContain('ZC2026A02030001')
    expect(wrapper.text()).toContain('示例保管人')
    expect(wrapper.text()).toContain('示例教室')
  })

  it('扫码报修:展示设备信息与保修提示、维修单号', async () => {
    const wrapper = mount(AssetMobile)
    await clickTab(wrapper, 1)
    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('ZC2026A02030001X')
    await inputs[1].setValue('示例故障:无法开机')
    const buttons = wrapper.findAll('button')
    // 入口按钮与操作按钮同名,取最后一个才是操作按钮。
    const action = buttons.filter((b) => b.text() === '扫码报修').at(-1)!
    await action.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('示例资产')
    expect(wrapper.text()).toContain('保内,请走厂商保修')
    expect(wrapper.text()).toContain('WX-示例')
  })

  it('借用/领用确认:确认后显示领用单号与在用提示', async () => {
    const wrapper = mount(AssetMobile)
    await clickTab(wrapper, 2)
    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('3')
    await inputs[1].setValue('ZC2026A02030001X')
    const buttons = wrapper.findAll('button')
    await buttons.find((b) => b.text() === '确认接收')!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('LY-示例')
    expect(wrapper.text()).toContain('已确认接收')
  })

  it('盘点作业:扫码后显示盘点结果', async () => {
    const wrapper = mount(AssetMobile)
    await clickTab(wrapper, 3)
    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('5')
    await inputs[1].setValue('ZC2026A02030001X')
    const buttons = wrapper.findAll('button')
    await buttons.find((b) => b.text() === '扫码盘点')!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('盘点记录成功')
  })

  it('#49 复核补:断网扫码离线暂存,重挂载后显示待补传', async () => {
    localStorage.clear()
    vi.mocked(fetch).mockRejectedValueOnce(new Error('Failed to fetch'))
    const wrapper = mount(AssetMobile)
    await clickTab(wrapper, 3)
    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('5')
    await inputs[1].setValue('ZC2026A02030001X')
    const buttons = wrapper.findAll('button')
    await buttons.find((b) => b.text() === '扫码盘点')!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('已离线暂存')
    const stored = JSON.parse(localStorage.getItem('asset-offline-inventory-scans') ?? '[]') as unknown[]
    expect(stored).toHaveLength(1)
    // 重挂载:待补传提示仍在。
    const wrapper2 = mount(AssetMobile)
    await clickTab(wrapper2, 3)
    expect(wrapper2.text()).toContain('待补传离线记录 1 条')
    localStorage.clear()
  })

  it('#49 复核补:重新同步把离线记录补传并清空', async () => {
    localStorage.setItem('asset-offline-inventory-scans', JSON.stringify([{
      task_id: 5, label_code: 'ZC2026A02030001X', saved_at: '2026-11-15T00:00:00Z',
    }]))
    const wrapper = mount(AssetMobile)
    await clickTab(wrapper, 3)
    expect(wrapper.text()).toContain('待补传离线记录 1 条')
    const buttons = wrapper.findAll('button')
    await buttons.find((b) => b.text() === '重新同步')!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('已补传 1 条离线盘点记录')
    expect(localStorage.getItem('asset-offline-inventory-scans')).toBeNull()
  })
})
