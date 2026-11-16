import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import AssetCirculation from './AssetCirculation.vue'

vi.stubGlobal('fetch', vi.fn((url: string) => {
  if (url.includes('/issues')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve([{
        id: 1, doc_no: 'LY-20261115-0001', asset_id: 1, applicant_id: 7,
        applicant_name: '示例申请人', use_dept: '示例教研组', reason: '示例教学使用',
        status: '待发放', approval_instance_id: 1, issued_by: null,
        issued_at: null, confirmed_at: null, created_at: '2026-11-15T00:00:00Z',
      }]),
    })
  }
  if (url.includes('/borrows')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve([{
        id: 2, doc_no: 'JY-20261115-0001', asset_id: 1, borrower_id: 7,
        borrower_name: '示例借用人', reason: '示例借用', due_at: '2026-11-20T17:00:00Z',
        status: '借用中', is_overdue: false, overdue_days: 0, escalated: false,
        reminded_before_due: false, returned_at: null, created_at: '2026-11-15T00:00:00Z',
      }]),
    })
  }
  if (url.includes('/reservations')) {
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) })
  }
  if (url.includes('/returns')) {
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) })
  }
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
}))

describe('领用借用归还页', () => {
  it('展示领用单与发放入口、借用单列表', async () => {
    const wrapper = mount(AssetCirculation)
    await flushPromises()
    expect(wrapper.text()).toContain('领用借用归还')
    expect(wrapper.text()).toContain('长期领用申请')
    expect(wrapper.text()).toContain('LY-20261115-0001')
    expect(wrapper.text()).toContain('发放 LY-20261115-0001')
    expect(wrapper.text()).toContain('领用确认(扫码)')
    expect(wrapper.text()).toContain('长期领用三步')
    expect(wrapper.text()).toContain('选中扫码')
    expect(wrapper.text()).toContain('输入资产编号或名称搜索')
  })
})
