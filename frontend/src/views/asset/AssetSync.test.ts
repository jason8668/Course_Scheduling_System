import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import AssetSync from './AssetSync.vue'

vi.stubGlobal('fetch', vi.fn((url: string) => {
  if (url.includes('/sync/boundary')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        live_api: false, adapter: 'template_export', template_version: '当期模板',
        boundary_note: '官方系统的账号、权限、模板版本与开放政策由财政及主管部门决定。',
        execution_note: '一期为模板交换,实时接口未开放:本次同步只生成官方当期模板导入文件。',
        mapping_count: 13,
      }),
    })
  }
  if (url.includes('/sync/pool')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        items: [], total: 2, total_value: 6000, groups: {},
      }),
    })
  }
  if (url.includes('/sync/batches')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve([{
        id: 1, batch_no: 'TB20261115-0001', selection_batch_no: 'GX20261115-0001',
        status: '已导出', total_count: 1, total_value: 3000, blocked_count: 1,
        items: [], blocked: [], created_at: '2026-11-15T00:00:00Z',
      }]),
    })
  }
  if (url.includes('/sync/pending-changes')) {
    return Promise.resolve({
      ok: true, status: 200, json: () => Promise.resolve([]),
    })
  }
  if (url.includes('/sync/unsynced-stats')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve([
        { category_code: 'A0203', count: 1, total_value: 3000 },
      ]),
    })
  }
  if (url.includes('/sync/logs')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve([{
        id: 1, action: '生成批次', batch_no: 'TB20261115-0001', asset_id: 10,
        asset_code: 'ZC2026A02030001', operator_id: 2, operator_name: 'am',
        result: '成功', detail: '示例同步日志', created_at: '2026-11-15T00:00:00Z',
      }]),
    })
  }
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
}))

describe('同步执行与对账页', () => {
  it('展示模板交换边界提示、待同步池、批次与未同步统计', async () => {
    const wrapper = mount(AssetSync)
    await flushPromises()
    expect(wrapper.text()).toContain('同步执行与对账')
    expect(wrapper.text()).toContain('一期为模板交换,实时接口未开放')
    expect(wrapper.text()).toContain('待同步池:共 2 件,总价值 6000 元')
    expect(wrapper.text()).toContain('TB20261115-0001')
    expect(wrapper.text()).toContain('A0203')
    expect(wrapper.text()).toContain('生成批次')
    expect(wrapper.text()).toContain('同步前校验')
    expect(wrapper.text()).toContain('编号回填')
    expect(wrapper.text()).toContain('生成批次')
    expect(wrapper.text()).toContain('月度对账清单')
  })
})
