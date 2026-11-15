import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import AssetTransfer from './AssetTransfer.vue'

vi.stubGlobal('fetch', vi.fn((url: string) => {
  if (url.includes('/transfers')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve([{
        id: 1, doc_no: 'DB-20261115-0001', asset_id: 1, from_dept: '示例总务处',
        to_dept: '示例教务处', to_custodian_id: 8, to_custodian_name: '示例接收人',
        to_room_name: '示例教室', reason: '示例调拨', amount: 3000, status: '待调入确认',
        approval_instance_id: 1, in_confirmed_by: null, in_confirmed_at: null,
        created_at: '2026-11-15T00:00:00Z',
      }]),
    })
  }
  if (url.includes('/handovers')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve([{
        id: 2, doc_no: 'YJ-20261115-0001', from_user_id: 7, from_user_name: '示例移交人',
        to_user_id: 8, to_user_name: '示例接收人', reason_type: '离职', status: '待移交',
        is_overdue: false, created_at: '2026-11-15T00:00:00Z', items: [],
      }]),
    })
  }
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
}))

describe('调拨与移交页', () => {
  it('展示调拨单与调入确认入口、移交单与逐件确认入口', async () => {
    const wrapper = mount(AssetTransfer)
    await flushPromises()
    expect(wrapper.text()).toContain('调拨与移交')
    expect(wrapper.text()).toContain('部门间调拨')
    expect(wrapper.text()).toContain('DB-20261115-0001')
    expect(wrapper.text()).toContain('调入确认 DB-20261115-0001')
    expect(wrapper.text()).toContain('离职/调岗/退休移交')
    expect(wrapper.text()).toContain('YJ-20261115-0001')
    expect(wrapper.text()).toContain('逐件扫码确认')
    expect(wrapper.text()).toContain('未接人事系统')
  })
})
