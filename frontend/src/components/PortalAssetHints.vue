<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { getPortalAssetHints } from '@/api/asset'
import type { PortalHints } from '@/api/asset'

// Portal 首页资产提示卡(资产一期复核):只读汇总,接口失败整卡隐藏,绝不编数据。
// 角色口径以后端为准:我的(所有人)、管理(admin/asset_admin)、
// 领导(director/admin);后端对不可见字段回 null,前端只渲染非 null 项。
// 资产页尚无路由(2026-11-15),本卡 v1 只显示数字,不挂入口链接;
// 路由接线后按 portal-home-hints.md 的补丁再补链接。
const hints = ref<PortalHints | null>(null)

interface HintCell { label: string; value: string; sub?: string }

function money(v: number): string {
  return `¥${v.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`
}

const myCells = computed<HintCell[]>(() => {
  const h = hints.value
  if (!h) return []
  const borrow = h.my_borrow_overdue > 0
    ? `逾期 ${h.my_borrow_overdue} 条 · 将到期 ${h.my_borrow_due_soon} 条`
    : (h.my_borrow_due_soon > 0 ? `将到期 ${h.my_borrow_due_soon} 条` : '无到期借用')
  const repair = h.my_repair_open === 0
    ? '无进行中报修'
    : (h.my_repair_pending_confirm > 0
      ? `待确认 ${h.my_repair_pending_confirm} 条 · 进行中 ${h.my_repair_open - h.my_repair_pending_confirm} 条`
      : `进行中 ${h.my_repair_open} 条`)
  return [
    { label: '我的资产', value: `${h.my_assets_total} 件` },
    { label: '我的借用', value: borrow },
    { label: '我的报修', value: repair },
  ]
})

const adminCells = computed<HintCell[]>(() => {
  const h = hints.value
  if (!h || h.admin_pending_approval === null) return []
  return [
    { label: '待审批', value: `${h.admin_pending_approval} 条` },
    { label: '借用逾期', value: `${h.admin_borrow_overdue ?? 0} 条`, sub: '全校' },
    { label: '维修待确认', value: `${h.admin_repair_pending_confirm ?? 0} 条` },
    {
      label: '盘点任务',
      value: `${h.admin_inventory_open_tasks ?? 0} 个未完成任务`,
      sub: `进行中方案 ${h.admin_inventory_open_plans ?? 0} 个`,
    },
    { label: '处置待办', value: `${h.admin_disposal_open ?? 0} 单` },
    { label: '同步积压', value: `${h.admin_sync_pending ?? 0} 件待同步` },
  ]
})

const leaderCells = computed<HintCell[]>(() => {
  const h = hints.value
  if (!h || h.leader_idle_count === null) return []
  const byStatus = h.leader_disposal_by_status ?? {}
  const parts = Object.entries(byStatus)
    .filter(([, n]) => n > 0)
    .map(([s, n]) => `${s} ${n}`)
  return [
    {
      label: '闲置资产',
      value: `${h.leader_idle_count} 件`,
      sub: `原值合计 ${money(h.leader_idle_value ?? 0)}`,
    },
    {
      label: '待处置汇总',
      value: `待处理 ${h.leader_disposal_open ?? 0} 单`,
      sub: parts.length ? parts.join(' · ') : undefined,
    },
  ]
})

const allCells = computed<HintCell[]>(() => [
  ...myCells.value, ...adminCells.value, ...leaderCells.value,
])

// 全部可见数都为 0(新账号、名下无资产、无待办)才画空状态,否则画格子。
const hasAnything = computed(() => {
  const h = hints.value
  if (!h) return false
  return h.my_assets_total > 0 || h.my_borrow_overdue > 0 || h.my_borrow_due_soon > 0
    || h.my_repair_open > 0
    || (h.admin_pending_approval ?? 0) > 0 || (h.admin_borrow_overdue ?? 0) > 0
    || (h.admin_repair_pending_confirm ?? 0) > 0
    || (h.admin_inventory_open_tasks ?? 0) > 0 || (h.admin_disposal_open ?? 0) > 0
    || (h.admin_sync_pending ?? 0) > 0
    || (h.leader_idle_count ?? 0) > 0 || (h.leader_disposal_open ?? 0) > 0
})

onMounted(async () => {
  try {
    hints.value = await getPortalAssetHints()
  } catch {
    // 静默缺失:整卡隐藏,不拖垮首页其它卡。
    hints.value = null
  }
})
</script>

<template>
  <section v-if="hints" class="ios-section" data-testid="portal-asset-hints">
    <div class="ios-section-title">资产提醒</div>
    <div class="asset-hints-card">
      <div v-if="hasAnything" class="asset-hints-grid">
        <div v-for="cell in allCells" :key="cell.label" class="hint-stat">
          <div class="hint-stat-label">{{ cell.label }}</div>
          <div class="hint-stat-value">{{ cell.value }}</div>
          <div v-if="cell.sub" class="hint-stat-sub">{{ cell.sub }}</div>
        </div>
      </div>
      <div v-else class="asset-hints-empty">
        <div class="hint-empty-text">暂无资产待办事项</div>
      </div>
    </div>
  </section>
</template>

<style scoped>
/* 走 Portal 的蓝,与总入口其它卡同色同版式:卡片 #DCE9FD、内格 #EAF3FE
   加蓝边框;Portal.vue 的样式是 scoped,本组件自带一份,不依赖它。
   格子沿用今日概览 portal-stat 的左对齐,不另起居中排版。 */
.ios-section { margin-top: 28px; }
.ios-section-title { padding: 0 4px 8px; font-size: 14px; color: #5b7ba6; }
.asset-hints-card {
  background: #dce9fd;
  border: 1px solid rgba(0, 122, 255, 0.16);
  border-radius: 20px;
  box-shadow: 0 6px 20px rgba(0, 122, 255, 0.1);
  padding: 16px 20px;
}
.asset-hints-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
.hint-stat { background: #eaf3fe; border: 1px solid rgba(0, 122, 255, 0.18); border-radius: 14px; padding: 14px 16px; }
.hint-stat-label { font-size: 13px; color: #5b7ba6; margin-bottom: 6px; }
.hint-stat-value { font-size: 17px; font-weight: 600; color: #1d1d1f; }
.hint-stat-sub { font-size: 13px; font-weight: 400; color: #5b7ba6; margin-top: 4px; }
.asset-hints-empty { text-align: center; padding: 32px 20px; }
.hint-empty-text { font-size: 15px; color: #5b7ba6; }
</style>
