import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import AssetCard from './AssetCard.vue'

async function mountCard(query: Record<string, string> = { id: '1' }) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/asset/cards', name: 'asset-card', component: AssetCard },
      { path: '/asset/ledger', name: 'asset-ledger', component: { template: '<div />' } },
    ],
  })
  await router.push({ name: 'asset-card', query })
  await router.isReady()
  return mount(AssetCard, { global: { plugins: [router] } })
}

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
    const wrapper = await mountCard()
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

  it('不带 id 进来不再空白:给搜索提示,不调不存在的资产', async () => {
    const wrapper = await mountCard({})
    await flushPromises()
    expect(wrapper.text()).toContain('资产卡')
    expect(wrapper.text()).toContain('还没有打开任何资产卡')
    expect(wrapper.text()).toContain('打开资产卡')
  })

  // ── 附件直传 #12 ──
  it('有“上传附件”按钮:选文件后调 multipart 上传端点,成功显示已上传件数', async () => {
    const uploaded = [{
      id: 99, asset_id: 1, file_type: '设备照片', file_name: 'photo.jpg',
      file_path: '1/photo.jpg', file_size: 4, acceptance_id: null,
      uploaded_by: 1, created_at: null,
    }]
    const fetchMock = vi.fn((url: string, _init?: RequestInit) => {
      if (url.includes('/attachments/upload')) {
        return Promise.resolve({
          ok: true, status: 201, json: () => Promise.resolve(uploaded),
        })
      }
      if (url.includes('/attachments')) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) })
      }
      if (url.includes('/timeline')) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) })
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(CARD) })
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = await mountCard()
    await flushPromises()
    expect(wrapper.text()).toContain('上传附件')
    const input = wrapper.find('input[type="file"]')
    expect(input.exists()).toBe(true)
    Object.defineProperty(input.element, 'files', {
      value: [new File(['fake'], 'photo.jpg', { type: 'image/jpeg' })],
    })
    await input.trigger('change')
    await flushPromises()
    const uploadCall = fetchMock.mock.calls.find(([url]) =>
      String(url).includes('/attachments/upload'))
    expect(uploadCall).toBeDefined()
    expect((uploadCall![1] as RequestInit).body).toBeInstanceOf(FormData)
    expect(wrapper.text()).toContain('已上传 1 个附件')
  })

  it('上传失败显示后端返回的原因', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.includes('/attachments/upload')) {
        return Promise.resolve({
          ok: false, status: 400,
          json: () => Promise.resolve({ detail: '不支持的文件类型: bad.exe' }),
        })
      }
      if (url.includes('/attachments')) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) })
      }
      if (url.includes('/timeline')) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) })
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(CARD) })
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = await mountCard()
    await flushPromises()
    const input = wrapper.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', {
      value: [new File(['fake'], 'bad.exe', { type: 'application/octet-stream' })],
    })
    await input.trigger('change')
    await flushPromises()
    expect(wrapper.text()).toContain('不支持的文件类型: bad.exe')
    expect(wrapper.text()).not.toContain('已上传')
  })
})
