import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import AssetDepartments from './AssetDepartments.vue'

const SEED_DEPTS = [
  {
    id: 1, name: '教务处', code: 'JW01', parent_id: null, parent_name: null,
    is_active: true, manage_count: 2, use_count: 1, asset_count: 3,
  },
  {
    id: 2, name: '总务处', code: 'ZW01', parent_id: null, parent_name: null,
    is_active: true, manage_count: 0, use_count: 0, asset_count: 0,
  },
]

const SEED_UNCLAIMED = [
  { name: '教务', manage_count: 1, use_count: 1, total_count: 2 },
]

const fetchedUrls: string[] = []
vi.stubGlobal('fetch', vi.fn((url: string) => {
  fetchedUrls.push(url)
  const body = url.includes('/unclaimed') ? SEED_UNCLAIMED : SEED_DEPTS
  return Promise.resolve({
    ok: true, status: 200,
    json: () => Promise.resolve(body),
  })
}))

describe('部门字典页(#76)', () => {
  it('展示字典部门列表与待认领区', async () => {
    const wrapper = mount(AssetDepartments)
    await flushPromises()
    expect(fetchedUrls).toContain('/api/asset/departments')
    expect(fetchedUrls).toContain('/api/asset/departments/unclaimed')
    expect(wrapper.text()).toContain('教务处')
    expect(wrapper.text()).toContain('总务处')
    expect(wrapper.text()).toContain('JW01')
    expect(wrapper.text()).toContain('待认领')
    expect(wrapper.text()).toContain('教务')
    expect(wrapper.text()).toContain('新建字典并认领')
    expect(wrapper.text()).toContain('并入')
    expect(wrapper.text()).toContain('重新对齐')
  })
})
