import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import PortalAssetHints from './PortalAssetHints.vue'

// Portal 首页资产提示卡:用 URL 分发的 fetch stub 回固定夹具,不碰后端。
function json(data: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(data) })
}

const ADMIN_HINTS = {
  my_assets_total: 3,
  my_borrow_overdue: 1,
  my_borrow_due_soon: 2,
  my_repair_open: 2,
  my_repair_pending_confirm: 1,
  admin_pending_approval: 2,
  admin_borrow_overdue: 4,
  admin_repair_pending_confirm: 1,
  admin_inventory_open_plans: 1,
  admin_inventory_open_tasks: 3,
  admin_disposal_open: 2,
  admin_sync_pending: 5,
  leader_idle_count: 6,
  leader_idle_value: 12345.67,
  leader_disposal_open: 3,
  leader_disposal_by_status: { '待鉴定': 1, '待审批': 1, '审批通过': 0, '待官方批复': 1, '已批复': 0 },
}

const TEACHER_HINTS = {
  ...ADMIN_HINTS,
  admin_pending_approval: null,
  admin_borrow_overdue: null,
  admin_repair_pending_confirm: null,
  admin_inventory_open_plans: null,
  admin_inventory_open_tasks: null,
  admin_disposal_open: null,
  admin_sync_pending: null,
  leader_idle_count: null,
  leader_idle_value: null,
  leader_disposal_open: null,
  leader_disposal_by_status: null,
}

const EMPTY_HINTS = {
  my_assets_total: 0,
  my_borrow_overdue: 0,
  my_borrow_due_soon: 0,
  my_repair_open: 0,
  my_repair_pending_confirm: 0,
  admin_pending_approval: null,
  admin_borrow_overdue: null,
  admin_repair_pending_confirm: null,
  admin_inventory_open_plans: null,
  admin_inventory_open_tasks: null,
  admin_disposal_open: null,
  admin_sync_pending: null,
  leader_idle_count: null,
  leader_idle_value: null,
  leader_disposal_open: null,
  leader_disposal_by_status: null,
}

function stubFetch(data: unknown) {
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    if (String(url).includes('/workspace/portal-hints')) return json(data)
    return Promise.reject(new Error(`unexpected url ${url}`))
  }))
}

describe('PortalAssetHints', () => {
  it('管理员/资产管理员/领导口径:11 格全显示,数字取自接口', async () => {
    stubFetch(ADMIN_HINTS)
    const wrapper = mount(PortalAssetHints)
    await flushPromises()
    const text = wrapper.text()
    expect(wrapper.find('[data-testid="portal-asset-hints"]').exists()).toBe(true)
    expect(wrapper.findAll('.hint-stat')).toHaveLength(11)
    for (const label of ['我的资产', '我的借用', '我的报修', '待审批', '借用逾期',
      '维修待确认', '盘点任务', '处置待办', '同步积压', '闲置资产', '待处置汇总']) {
      expect(text).toContain(label)
    }
    expect(text).toContain('3 件')
    expect(text).toContain('逾期 1 条 · 将到期 2 条')
    expect(text).toContain('待确认 1 条 · 进行中 1 条')
    expect(text).toContain('待审批')
    expect(text).toContain('3 个未完成任务')
    expect(text).toContain('进行中方案 1 个')
    expect(text).toContain('5 件待同步')
    expect(text).toContain('6 件')
    expect(text).toContain('原值合计 ¥12,345.67')
    expect(text).toContain('待处理 3 单')
    expect(text).toContain('待鉴定 1 · 待审批 1 · 待官方批复 1')
    vi.unstubAllGlobals()
  })

  it('普通教师:只显示我的 3 格,不显示管理与领导项', async () => {
    stubFetch(TEACHER_HINTS)
    const wrapper = mount(PortalAssetHints)
    await flushPromises()
    const text = wrapper.text()
    expect(wrapper.findAll('.hint-stat')).toHaveLength(3)
    expect(text).toContain('我的资产')
    expect(text).toContain('我的借用')
    expect(text).toContain('我的报修')
    // “我的借用”格的值含“逾期 1 条”,与管理口径的“借用逾期”标签拼起来
    // 会误判,故教师口径只按格数 + 其余标签断言,不用 not.toContain('借用逾期')。
    for (const label of ['待审批', '维修待确认', '盘点任务',
      '处置待办', '同步积压', '闲置资产', '待处置汇总']) {
      expect(text).not.toContain(label)
    }
    vi.unstubAllGlobals()
  })

  it('全部为 0:显示空状态,不画格子', async () => {
    stubFetch(EMPTY_HINTS)
    const wrapper = mount(PortalAssetHints)
    await flushPromises()
    expect(wrapper.text()).toContain('暂无资产待办事项')
    expect(wrapper.find('.hint-stat').exists()).toBe(false)
    vi.unstubAllGlobals()
  })

  it('接口失败:整卡隐藏', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('down'))))
    const wrapper = mount(PortalAssetHints)
    await flushPromises()
    expect(wrapper.find('[data-testid="portal-asset-hints"]').exists()).toBe(false)
    vi.unstubAllGlobals()
  })
})
