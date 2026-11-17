// 学校资产管理系统一期地基批:资产模块 API 封装(前缀 /api/asset)。
// 复用现有登录与鉴权,不新建登录入口;资产操作按八类角色授权。
// 注意:client.request 会在 path 前补 /api,故此处 path 以 /asset 开头。

import { apiDelete, apiGet, apiPost } from '@/api/client'
import type { ApiError } from '@/api/client'

export interface AssetCategory {
  id: number
  code: string
  name: string
  level: number
  parent_code: string | null
  is_reportable: boolean
  origin: string
  is_active: boolean
  sort_order: number
}

export interface FinanceMap {
  id: number
  category_code: string
  finance_subject_code: string
  finance_subject_name: string
  is_default: boolean
  note: string
}

export interface AssetRole {
  value: string
  label: string
}

export interface SyncAdapterInfo {
  adapter: string
  available: string[]
  live_api: boolean
  note: string
}

/** 资产分类字典(只读展示用);上报分类代码与名称已锁定,不可改。 */
export const listAssetCategories = (params?: {
  level?: number
  parent_code?: string
  is_active?: boolean
}): Promise<AssetCategory[]> => {
  const query = new URLSearchParams()
  if (params?.level !== undefined) query.set('level', String(params.level))
  if (params?.parent_code) query.set('parent_code', params.parent_code)
  if (params?.is_active !== undefined) query.set('is_active', String(params.is_active))
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return apiGet<AssetCategory[]>(`/asset/categories${suffix}`)
}

/** 某分类的财务科目对照表。 */
export const listFinanceMap = (code: string): Promise<FinanceMap[]> =>
  apiGet<FinanceMap[]>(`/asset/categories/${encodeURIComponent(code)}/finance-map`)

/** 资产八类角色清单(供前端展示)。 */
export const listAssetRoles = (): Promise<{ roles: AssetRole[] }> =>
  apiGet<{ roles: AssetRole[] }>('/asset/roles')

/** 对接适配层状态:一期只有模板导出,无实时官方接口。 */
export const getSyncAdapterInfo = (): Promise<SyncAdapterInfo> =>
  apiGet<SyncAdapterInfo>('/asset/sync/adapter')

/** 编码规则预览:按当前启用规则生成下一个校内编号(不建卡)。 */
export const previewAssetCode = (categoryCode: string): Promise<{
  asset_code: string
  label_code: string
}> => apiGet(`/asset/code-rules/preview?category_code=${encodeURIComponent(categoryCode)}`)

/** 资产卡(台账/入库/勾选)——第 2 批新增字段。 */
export interface AssetCard {
  id: number
  asset_code: string
  official_code: string | null
  label_code: string
  name: string
  category_code: string
  spec_model: string | null
  unit: string
  acquired_date: string | null
  acquire_method: string | null
  source: string | null
  supplier: string | null
  original_value: number | null
  funding_source: string | null
  voucher_no: string | null
  status: string
  manage_dept: string | null
  use_dept: string | null
  custodian_name: string | null
  campus: string | null
  building: string | null
  room_name: string | null
  borrow_status: string
  attributes: Record<string, unknown> | null
  ext: Record<string, unknown> | null
  sync_status: string
  is_retired: boolean
  batch_no: string | null
  acceptance_id: number | null
  is_booked: boolean
  booked_at: string | null
  last_used_at: string | null
  is_idle: boolean
  idle_reason: string | null
  created_at: string | null
}

export interface AssetSearchParams {
  category_code?: string
  manage_dept?: string
  use_dept?: string
  custodian_name?: string
  room_id?: number
  room_name?: string
  status?: string
  sync_status?: string
  acquire_method?: string
  funding_source?: string
  acquired_year?: number
  min_value?: number
  max_value?: number
  batch_no?: string
  is_booked?: boolean
  is_idle?: boolean
  q?: string
  sort_by?: string
  sort_dir?: 'asc' | 'desc'
  limit?: number
  offset?: number
}

export interface BulkItemResult {
  asset_id: number | null
  asset_code: string | null
  ok: boolean
  reason: string
}

export interface BulkResult {
  succeeded: BulkItemResult[]
  failed: BulkItemResult[]
  batch_no: string | null
}

export interface AssetAttachment {
  id: number
  asset_id: number
  file_type: string
  file_name: string
  file_path: string
  file_size: number | null
  acceptance_id: number | null
  uploaded_by: number | null
  created_at: string | null
}

export interface AssetLabel {
  asset_id: number
  asset_code: string
  label_code: string
  name: string
  manage_dept: string | null
  valid: boolean
}

export interface AssetIdle {
  id: number
  asset_code: string
  name: string
  category_code: string
  manage_dept: string | null
  custodian_name: string | null
  status: string
  original_value: number | null
  acquired_date: string | null
  last_used_at: string | null
  idle_reason: string | null
}

export interface Acceptance {
  id: number
  acceptance_no: string
  intake_type: string
  status: string
  source_doc: Record<string, unknown> | null
  acceptors: string[] | null
  accepted_by: number | null
  accepted_at: string | null
  comment: string
  batch_no: string | null
  created_at: string | null
}

export interface SyncPoolItem {
  asset_id: number
  asset_code: string
  name: string
  category_code: string
  manage_dept: string | null
  original_value: number | null
  sync_status: string
  selected_by: number | null
  selected_at: string | null
  selection_batch_no: string | null
}

export interface SyncPool {
  items: SyncPoolItem[]
  total: number
  total_value: number
  groups: Record<string, { count: number; total_value: number }>
}

/** 六类入库入口(#19~#24)。 */
export const INTAKE_TYPES = [
  { value: 'gov_purchase', label: '政府采购到货入库' },
  { value: 'self_purchase', label: '自行采购入库' },
  { value: 'donation', label: '捐赠资产入库' },
  { value: 'transfer_in', label: '上级调拨入库' },
  { value: 'self_built', label: '自建/在建转固入库' },
  { value: 'inventory_surplus', label: '盘盈补记入库' },
] as const

function searchQuery(params: AssetSearchParams): string {
  const query = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') query.set(k, String(v))
  }
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return suffix
}

/** 多维组合查询台账(#8)。 */
export const searchAssets = (params: AssetSearchParams = {}): Promise<{
  items: AssetCard[]
  total: number
}> => apiGet<{ items: AssetCard[]; total: number }>(`/asset/ledger/search${searchQuery(params)}`)

/** 管理员:全帐号一览(用户名/姓名/角色),供移交选人用;非管理员调此接口会 403,调用方须兜底回手填 id。 */
export interface AssetUser {
  id: number
  username: string
  display_name: string
  roles: string[]
}
export const listAssetUsers = (): Promise<AssetUser[]> => apiGet<AssetUser[]>('/users')

/** 单张资产卡(#10):四区 + 扩展区 + 入账/闲置/批次。 */
export const getAssetCard = (assetId: number): Promise<AssetCard> =>
  apiGet<AssetCard>(`/asset/assets/${assetId}`)

/** 台账导出(#9):返回下载地址,浏览器直接打开下载 Excel。 */
export const assetExportUrl = (params: AssetSearchParams = {}, includeExt = false): string => {
  const query = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') query.set(k, String(v))
  }
  query.set('include_ext', String(includeExt))
  return `/api/asset/ledger/export?${query.toString()}`
}

/** 附件归档(#12)。 */
export const listAssetAttachments = (assetId: number): Promise<AssetAttachment[]> =>
  apiGet<AssetAttachment[]>(`/asset/assets/${assetId}/attachments`)
export const uploadAssetAttachment = (assetId: number, body: {
  file_type: string; file_name: string; file_path: string; file_size?: number
}): Promise<AssetAttachment> =>
  apiPost<AssetAttachment>(`/asset/assets/${assetId}/attachments`, body)
/** 附件直传(#12):multipart 多文件上传。client.request 只发 JSON,故此处直接用
 * fetch 发 FormData;失败时抛后端返回的 detail,调用方直接展示。 */
export const uploadAssetAttachmentFiles = async (
  assetId: number,
  files: File[],
  fileType = '其他',
): Promise<AssetAttachment[]> => {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  form.append('file_type', fileType)
  const resp = await fetch(`/api/asset/assets/${assetId}/attachments/upload`, {
    method: 'POST',
    credentials: 'include',
    body: form,
  })
  if (!resp.ok) {
    let detail: string | undefined
    try {
      detail = (await resp.json())?.detail
    } catch {
      detail = undefined
    }
    const err = new Error(detail || `API 错误 ${resp.status}`) as ApiError
    err.status = resp.status
    err.detail = detail
    throw err
  }
  return resp.json() as Promise<AssetAttachment[]>
}
export const deleteAssetAttachment = (attachmentId: number): Promise<{ deleted: boolean }> =>
  apiDelete<{ deleted: boolean }>(`/asset/attachments/${attachmentId}`)

/** 批量维护(#13)。 */
export const bulkUpdateAssets = (body: {
  asset_ids: number[]; custodian_name?: string; custodian_user_id?: number
  room_name?: string; room_id?: number; manage_dept?: string; use_dept?: string
  atomic?: boolean
}): Promise<BulkResult> => apiPost<BulkResult>('/asset/assets/bulk-update', body)

/** 标签(#28)。 */
export const listAssetLabels = (ids: number[]): Promise<AssetLabel[]> =>
  apiGet<AssetLabel[]>(`/asset/ledger/labels?ids=${ids.join(',')}`)
export const printAssetLabels = (assetIds: number[]): Promise<AssetLabel[]> =>
  apiPost<AssetLabel[]>('/asset/ledger/labels/print', { asset_ids: assetIds })
export const reprintAssetLabel = (assetId: number): Promise<AssetLabel> =>
  apiPost<AssetLabel>(`/asset/assets/${assetId}/label/reprint`)
/** 二维码标签图(#28,复核补):标签码编成的 QR(SVG),直接作 <img> src。 */
export const assetLabelQrUrl = (assetId: number): string =>
  `/api/asset/assets/${assetId}/label/qr`

/** 闲置清单与刷新(#14)。 */
export const listIdleAssets = (): Promise<AssetIdle[]> =>
  apiGet<AssetIdle[]>('/asset/idle')
export const refreshIdleAssets = (thresholdDays?: number): Promise<{
  threshold_days: number; idle_count: number; idle_ids: number[]
}> => apiPost('/asset/idle/refresh', thresholdDays ? { threshold_days: thresholdDays } : {})

/** 验收单(#25)与建卡(#19~#24/#26)。 */
export const listAcceptances = (params?: { intake_type?: string; status?: string }): Promise<Acceptance[]> => {
  const query = new URLSearchParams()
  if (params?.intake_type) query.set('intake_type', params.intake_type)
  if (params?.status) query.set('status', params.status)
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return apiGet<Acceptance[]>(`/asset/acceptances${suffix}`)
}
export const createAcceptance = (body: {
  intake_type: string; source_doc?: Record<string, unknown>; acceptors?: string[]; comment?: string
}): Promise<Acceptance> => apiPost<Acceptance>('/asset/acceptances', body)
export const confirmAcceptance = (id: number, body: {
  result: '通过' | '不通过'; acceptors?: string[]; comment?: string
}): Promise<Acceptance> => apiPost<Acceptance>(`/asset/acceptances/${id}/confirm`, body)
export const createCardsFromAcceptance = (id: number, body: {
  items: Record<string, unknown>[]; batch_no?: string
}): Promise<BulkResult> => apiPost<BulkResult>(`/asset/acceptances/${id}/create-cards`, body)
export const bulkCreateFromAcceptance = (id: number, body: {
  template: Record<string, unknown>; quantity: number; batch_no?: string
}): Promise<BulkResult> => apiPost<BulkResult>(`/asset/acceptances/${id}/bulk-create`, body)

/** 待入账清单与回填(#27)。 */
export const listBookingPending = (month?: string): Promise<{
  items: AssetCard[]; total: number; total_value: number
}> => apiGet(`/asset/booking-pending${month ? `?month=${month}` : ''}`)
export const bookingPendingExportUrl = (month?: string): string =>
  `/api/asset/booking-pending/export${month ? `?month=${month}` : ''}`
export const confirmBooking = (assetId: number, voucherNo: string): Promise<AssetCard> =>
  apiPost<AssetCard>(`/asset/assets/${assetId}/book`, { voucher_no: voucherNo })

/** 手动勾选(#87/#88/#89/#90)。 */
export const selectForSync = (assetIds: number[]): Promise<BulkResult> =>
  apiPost<BulkResult>('/asset/sync/select', { asset_ids: assetIds })
export const selectByFilterForSync = (body: Record<string, unknown>): Promise<BulkResult> =>
  apiPost<BulkResult>('/asset/sync/select-by-filter', body)
export const unselectForSync = (assetIds: number[]): Promise<BulkResult> =>
  apiPost<BulkResult>('/asset/sync/unselect', { asset_ids: assetIds })
export const getSyncPool = (params?: { selection_batch_no?: string; manage_dept?: string }): Promise<SyncPool> => {
  const query = new URLSearchParams()
  if (params?.selection_batch_no) query.set('selection_batch_no', params.selection_batch_no)
  if (params?.manage_dept) query.set('manage_dept', params.manage_dept)
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return apiGet<SyncPool>(`/asset/sync/pool${suffix}`)
}
/** 执行地基种子数据补种(幂等,仅管理员)。 */
export const seedAssetFoundation = (): Promise<{ seeded: Record<string, number> }> =>
  apiPost<{ seeded: Record<string, number> }>('/asset/admin/seed')
/** 第 3 批:领用/借用/预约/归还/团体保管/调拨/移交/工作台(#30~#35/#37/#39/#40/#1/#2/#3/#6/#7)。 */

export interface IssueOrder {
  id: number
  doc_no: string
  asset_id: number
  applicant_id: number
  applicant_name: string
  use_dept: string | null
  reason: string
  status: string
  approval_instance_id: number | null
  issued_by: number | null
  issued_at: string | null
  confirmed_at: string | null
  created_at: string | null
}

export interface BorrowOrder {
  id: number
  doc_no: string
  asset_id: number
  borrower_id: number
  borrower_name: string
  reason: string
  due_at: string
  status: string
  is_overdue: boolean
  overdue_days: number
  escalated: boolean
  reminded_before_due: boolean
  returned_at: string | null
  created_at: string | null
}

export interface Reservation {
  id: number
  doc_no: string
  asset_id: number
  reserver_id: number
  reserver_name: string
  start_at: string
  end_at: string
  purpose: string
  status: string
  borrow_order_id: number | null
  released_at: string | null
  created_at: string | null
}

export interface ReturnOrder {
  id: number
  doc_no: string
  asset_id: number
  source_doc_type: string
  source_doc_id: number | null
  returner_id: number
  returner_name: string
  status: string
  result: string | null
  damage_note: string
  repair_order_id: number | null
  scanned_at: string | null
  created_at: string | null
}

export interface RepairOrder {
  id: number
  doc_no: string
  asset_id: number
  source: string
  source_doc_no: string | null
  reporter_id: number | null
  reporter_name: string
  description: string
  status: string
  // ── 第 4 批扩展字段(#43) ──
  photo_url: string | null
  assignee_id: number | null
  assignee_name: string | null
  vendor: string
  cost: number | null
  result: string
  pre_repair_status: string | null
  approval_instance_id: number | null
  confirmed_by: number | null
  confirmed_at: string | null
  closed_at: string | null
  created_at: string | null
}

export interface RepairScanResult {
  asset_id: number
  asset_code: string
  name: string
  status: string
  room_name: string | null
  custodian_name: string | null
  warranty_until: string | null
  in_warranty: boolean
  warranty_hint: string
  repair_order_id: number | null
  doc_no: string | null
  created: boolean
}

export interface RepairCostSummary {
  asset_id: number
  total_cost: number
  closed_count: number
  open_count: number
  threshold: number
}

export interface GroupCustody {
  id: number
  doc_no: string
  asset_id: number
  group_type: string
  group_name: string
  group_ref_id: number | null
  teacher_id: number
  teacher_name: string
  note: string
  is_active: boolean
  created_at: string | null
}

export interface TransferOrder {
  id: number
  doc_no: string
  asset_id: number
  from_dept: string | null
  to_dept: string
  to_custodian_id: number | null
  to_custodian_name: string | null
  to_room_name: string | null
  reason: string
  amount: number | null
  status: string
  approval_instance_id: number | null
  in_confirmed_by: number | null
  in_confirmed_at: string | null
  created_at: string | null
}

export interface HandoverItem {
  id: number
  handover_id: number
  asset_id: number
  asset_code: string
  status: string
  confirmed_by: number | null
  confirmed_at: string | null
}

export interface HandoverOrder {
  id: number
  doc_no: string
  from_user_id: number
  from_user_name: string
  to_user_id: number
  to_user_name: string
  reason_type: string
  status: string
  is_overdue: boolean
  created_at: string | null
  items: HandoverItem[]
}

export interface AssetReminder {
  id: number
  kind: string
  user_id: number | null
  target_type: string
  target_id: number | null
  title: string
  content: string
  level: string
  is_read: boolean
  is_dingtalk_sent: boolean
  created_at: string | null
}

export interface TodoItem {
  kind: string
  title: string
  detail: string
  target_type: string
  target_id: number | null
  due_at: string | null
  urgency: string
  urgency_rank: number
}

export interface TimelineEntry {
  time: string | null
  type: string
  title: string
  detail: string
  doc_no: string | null
  actor: string
}

/** 领用单(#30/#31):申请、发放、扫码确认。 */
export const createIssue = (body: {
  asset_id: number; use_dept?: string; reason?: string
}): Promise<IssueOrder> => apiPost<IssueOrder>('/asset/issues', body)
export const listIssues = (params?: { status?: string }): Promise<IssueOrder[]> => {
  const suffix = params?.status ? `?status=${encodeURIComponent(params.status)}` : ''
  return apiGet<IssueOrder[]>(`/asset/issues${suffix}`)
}
export const getIssue = (id: number): Promise<IssueOrder> =>
  apiGet<IssueOrder>(`/asset/issues/${id}`)
export const issueAsset = (id: number): Promise<IssueOrder> =>
  apiPost<IssueOrder>(`/asset/issues/${id}/issue`)
export const confirmIssueScan = (id: number, labelCode: string): Promise<IssueOrder> =>
  apiPost<IssueOrder>(`/asset/issues/${id}/confirm-scan`, { label_code: labelCode })

/** 借用单(#32)与逾期清单。 */
export const createBorrow = (body: {
  asset_id: number; reason?: string; due_at: string
}): Promise<BorrowOrder> => apiPost<BorrowOrder>('/asset/borrows', body)
export const listBorrows = (params?: { status?: string }): Promise<BorrowOrder[]> => {
  const suffix = params?.status ? `?status=${encodeURIComponent(params.status)}` : ''
  return apiGet<BorrowOrder[]>(`/asset/borrows${suffix}`)
}
export const listOverdueBorrows = (): Promise<BorrowOrder[]> =>
  apiGet<BorrowOrder[]>('/asset/borrows/overdue')
export const scanBorrowOverdue = (): Promise<{
  reminded: number[]; overdue: number[]; escalated: number[]
  pushed: { sent: number; skipped: number; failed: number }
}> => apiPost('/asset/workspace/scan-overdue')

/** 预约单(#33):创建、领用、取消、自动释放扫描。 */
export const createReservation = (body: {
  asset_id: number; start_at: string; end_at: string; purpose?: string
}): Promise<Reservation> => apiPost<Reservation>('/asset/reservations', body)
export const listReservations = (params?: { asset_id?: number; status?: string }): Promise<Reservation[]> => {
  const query = new URLSearchParams()
  if (params?.asset_id !== undefined) query.set('asset_id', String(params.asset_id))
  if (params?.status) query.set('status', params.status)
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return apiGet<Reservation[]>(`/asset/reservations${suffix}`)
}
export const checkoutReservation = (id: number): Promise<Reservation> =>
  apiPost<Reservation>(`/asset/reservations/${id}/checkout`)
export const cancelReservation = (id: number): Promise<Reservation> =>
  apiPost<Reservation>(`/asset/reservations/${id}/cancel`)
export const scanReleaseReservations = (): Promise<{ released: number[] }> =>
  apiPost('/asset/reservations/scan-release')

/** 归还单(#34)与维修占位单(B4 接入)。 */
export const createReturn = (body: {
  asset_id: number; source_doc_type?: string; source_doc_id?: number
}): Promise<ReturnOrder> => apiPost<ReturnOrder>('/asset/returns', body)
export const listReturns = (params?: { status?: string }): Promise<ReturnOrder[]> => {
  const suffix = params?.status ? `?status=${encodeURIComponent(params.status)}` : ''
  return apiGet<ReturnOrder[]>(`/asset/returns${suffix}`)
}
export const scanReturn = (id: number, body: {
  label_code: string; result: '完好' | '损坏'; damage_note?: string
}): Promise<ReturnOrder> => apiPost<ReturnOrder>(`/asset/returns/${id}/scan`, body)
export const listRepairs = (params?: { asset_id?: number; status?: string }): Promise<RepairOrder[]> => {
  const query = new URLSearchParams()
  if (params?.asset_id !== undefined) query.set('asset_id', String(params.asset_id))
  if (params?.status) query.set('status', params.status)
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return apiGet<RepairOrder[]>(`/asset/repairs${suffix}`)
}

/** 扫码报修(#42):扫标签码带出设备信息、存放地点与保修状态,保内提示走厂商保修。 */
export const scanRepair = (body: {
  label_code?: string; asset_id?: number; description?: string; photo_url?: string
}): Promise<RepairScanResult> => apiPost<RepairScanResult>('/asset/repairs/scan', body)
export const createRepair = (body: {
  label_code?: string; asset_id?: number; description?: string; photo_url?: string
}): Promise<RepairOrder> => apiPost<RepairOrder>('/asset/repairs', body)
/** 派单与维修处理(#43):派单/送修、登记维修方费用结果、报修人确认关闭。 */
export const dispatchRepair = (id: number, body: {
  assignee_id?: number; assignee_name?: string; vendor?: string; send_to_repair?: boolean
}): Promise<RepairOrder> => apiPost<RepairOrder>(`/asset/repairs/${id}/dispatch`, body)
export const recordRepair = (id: number, body: {
  vendor?: string; cost: number; result: string
}): Promise<RepairOrder> => apiPost<RepairOrder>(`/asset/repairs/${id}/record`, body)
export const confirmRepair = (id: number): Promise<RepairOrder> =>
  apiPost<RepairOrder>(`/asset/repairs/${id}/confirm`)
/** 维修费用累计查询(#43):单件资产累计维修费与工单数。 */
export const getRepairCostSummary = (assetId: number): Promise<RepairCostSummary> =>
  apiGet<RepairCostSummary>(`/asset/repairs/summary/by-asset?asset_id=${assetId}`)

/** 盘点方案与任务(#48)。 */
export interface InventoryPlan {
  id: number
  plan_no: string
  name: string
  plan_type: string
  note: string
  status: string
  created_at: string | null
}
export interface InventoryTask {
  id: number
  plan_id: number
  assignee_id: number
  assignee_name: string
  scope_dept: string | null
  scope_room_name: string | null
  scope_category_code: string | null
  due_at: string | null
  status: string
  created_at: string | null
}
export interface InventoryPlanDetail extends InventoryPlan {
  tasks: InventoryTask[]
  diff_counts: Record<string, number>
}
export interface InventoryRecord {
  id: number
  task_id: number
  asset_id: number | null
  label_code: string | null
  source: string
  status: string
  room_name: string | null
  custodian_name: string | null
  name: string | null
  description: string
  photo_url: string | null
  is_offline: boolean
  created_at: string | null
}
export interface InventoryDifference {
  id: number
  plan_id: number
  task_id: number
  asset_id: number | null
  asset_code: string | null
  asset_name: string | null
  diff_type: string
  status: string
  detail: string
  resolution: string
  involves_synced: boolean
  acceptance_id: number | null
  created_at: string | null
}
export interface InventoryReport {
  plan_id: number
  plan_no: string
  status: string
  total_expected: number
  total_scanned: number
  diff_counts: Record<string, number>
  unresolved: number
  synced_differences: InventoryDifference[]
  note: string
}

export const createInventoryPlan = (body: {
  name: string; plan_type?: string; note?: string
}): Promise<InventoryPlan> => apiPost<InventoryPlan>('/asset/inventory/plans', body)
export const listInventoryPlans = (params?: { status?: string }): Promise<InventoryPlan[]> => {
  const suffix = params?.status ? `?status=${encodeURIComponent(params.status)}` : ''
  return apiGet<InventoryPlan[]>(`/asset/inventory/plans${suffix}`)
}
export const getInventoryPlan = (id: number): Promise<InventoryPlanDetail> =>
  apiGet<InventoryPlanDetail>(`/asset/inventory/plans/${id}`)
export const createInventoryTask = (planId: number, body: {
  assignee_id: number; assignee_name?: string; scope_dept?: string
  scope_room_name?: string; scope_category_code?: string; due_at: string
}): Promise<InventoryTask> => apiPost<InventoryTask>(`/asset/inventory/plans/${planId}/tasks`, body)
export const listInventoryTasks = (params?: {
  plan_id?: number; assignee_id?: number; status?: string
}): Promise<InventoryTask[]> => {
  const query = new URLSearchParams()
  if (params?.plan_id !== undefined) query.set('plan_id', String(params.plan_id))
  if (params?.assignee_id !== undefined) query.set('assignee_id', String(params.assignee_id))
  if (params?.status) query.set('status', params.status)
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return apiGet<InventoryTask[]>(`/asset/inventory/tasks${suffix}`)
}
/** 手机扫码盘点(#49):范围外明确提示不计入;离线暂存弱网续传用 is_offline。 */
export const scanInventory = (taskId: number, body: {
  label_code: string; room_name?: string; custodian_id?: number
  custodian_name?: string; photo_url?: string; is_offline?: boolean
}): Promise<{
  in_scope: boolean; message: string; record_id: number | null
  asset_id: number | null; asset_code: string | null
}> => apiPost(`/asset/inventory/tasks/${taskId}/scan`, body)
export const unlabelledInventory = (taskId: number, body: {
  name: string; category_code?: string; description?: string; photo_url?: string
  room_name?: string; custodian_name?: string; is_offline?: boolean
}): Promise<InventoryRecord> => apiPost<InventoryRecord>(`/asset/inventory/tasks/${taskId}/unlabelled`, body)
export const listInventoryRecords = (taskId: number): Promise<InventoryRecord[]> =>
  apiGet<InventoryRecord[]>(`/asset/inventory/tasks/${taskId}/records`)
export const scanInventoryDue = (): Promise<{ reminded_tasks: number[] }> =>
  apiPost('/asset/inventory/scan-due')
/** 五类差异自动比对(#51)与差异处理(#52)。 */
export const computeInventoryDiffs = (taskId: number): Promise<{
  task_id: number; counts: Record<string, number>
}> => apiPost(`/asset/inventory/tasks/${taskId}/compute-diffs`)
export const listInventoryDifferences = (planId: number, params?: {
  task_id?: number; diff_type?: string
}): Promise<InventoryDifference[]> => {
  const query = new URLSearchParams()
  if (params?.task_id !== undefined) query.set('task_id', String(params.task_id))
  if (params?.diff_type) query.set('diff_type', params.diff_type)
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return apiGet<InventoryDifference[]>(`/asset/inventory/plans/${planId}/differences${suffix}`)
}
export const resolveInventoryDifference = (id: number, body: {
  action: 'shortage' | 'surplus_create' | 'correct_location' | 'correct_custodian' | 'note'
  resolution: string; name?: string; category_code?: string; original_value?: number
  room_name?: string; custodian_id?: number; custodian_name?: string
  new_room_name?: string; new_custodian_id?: number; new_custodian_name?: string
}): Promise<InventoryDifference> => apiPost<InventoryDifference>(`/asset/inventory/differences/${id}/resolve`, body)
export const closeInventoryPlan = (id: number, confirmNote?: string): Promise<InventoryPlan> =>
  apiPost<InventoryPlan>(`/asset/inventory/plans/${id}/close`, { confirm_note: confirmNote ?? '' })
export const getInventoryReport = (id: number): Promise<InventoryReport> =>
  apiGet<InventoryReport>(`/asset/inventory/plans/${id}/report`)

/** 团体保管单(#35)。 */
export const createGroupCustody = (body: {
  asset_id: number; group_type?: string; group_name: string
  group_ref_id?: number; teacher_id: number; note?: string
}): Promise<GroupCustody> => apiPost<GroupCustody>('/asset/group-custodies', body)
export const listGroupCustodies = (params?: { asset_id?: number }): Promise<GroupCustody[]> => {
  const suffix = params?.asset_id !== undefined ? `?asset_id=${params.asset_id}` : ''
  return apiGet<GroupCustody[]>(`/asset/group-custodies${suffix}`)
}

/** 调拨单(#37):发起、调入确认、完成。 */
export const createTransfer = (body: {
  asset_id: number; to_dept: string; to_custodian_id?: number
  to_room_name?: string; reason?: string
}): Promise<TransferOrder> => apiPost<TransferOrder>('/asset/transfers', body)
export const listTransfers = (params?: { status?: string }): Promise<TransferOrder[]> => {
  const suffix = params?.status ? `?status=${encodeURIComponent(params.status)}` : ''
  return apiGet<TransferOrder[]>(`/asset/transfers${suffix}`)
}
export const confirmInTransfer = (id: number): Promise<TransferOrder> =>
  apiPost<TransferOrder>(`/asset/transfers/${id}/confirm-in`)
export const finalizeTransfer = (id: number): Promise<TransferOrder> =>
  apiPost<TransferOrder>(`/asset/transfers/${id}/finalize`)

/** 移交单(#39/#40):按人员生成、逐件扫码确认、预警清单。 */
export const generateHandover = (body: {
  from_user_id: number; to_user_id: number; reason_type?: string
}): Promise<HandoverOrder> => apiPost<HandoverOrder>('/asset/handovers/generate', body)
export const listHandovers = (params?: { status?: string }): Promise<HandoverOrder[]> => {
  const suffix = params?.status ? `?status=${encodeURIComponent(params.status)}` : ''
  return apiGet<HandoverOrder[]>(`/asset/handovers${suffix}`)
}
export const confirmHandoverItem = (orderId: number, itemId: number, labelCode: string): Promise<HandoverOrder> =>
  apiPost<HandoverOrder>(`/asset/handovers/${orderId}/items/${itemId}/confirm`, { label_code: labelCode })
export const listHandoverWarnings = (): Promise<{
  items: (HandoverOrder & { overdue_days: number })[]; total: number; threshold_days: number
}> => apiGet('/asset/workspace/handover-warnings')
export const scanHandoverWarnings = (): Promise<{ warned: number[]; threshold_days: number }> =>
  apiPost('/asset/workspace/scan-handover-warnings')

/** 工作台(#1/#2/#3/#6):待办、我的资产、提醒、履历。 */
export const listMyTodos = (): Promise<TodoItem[]> =>
  apiGet<TodoItem[]>('/asset/workspace/todos')
export const listMyAssets = (): Promise<{ items: AssetCard[]; total: number }> =>
  apiGet<{ items: AssetCard[]; total: number }>('/asset/workspace/my-assets')

/** Portal 首页资产提示汇总:全部真实计数,无数据为 0;角色不可见的字段为 null。 */
export interface PortalHints {
  my_assets_total: number
  my_borrow_overdue: number
  my_borrow_due_soon: number
  my_repair_open: number
  my_repair_pending_confirm: number
  admin_pending_approval: number | null
  admin_borrow_overdue: number | null
  admin_repair_pending_confirm: number | null
  admin_inventory_open_plans: number | null
  admin_inventory_open_tasks: number | null
  admin_disposal_open: number | null
  admin_sync_pending: number | null
  leader_idle_count: number | null
  leader_idle_value: number | null
  leader_disposal_open: number | null
  leader_disposal_by_status: Record<string, number> | null
}
export const getPortalAssetHints = (): Promise<PortalHints> =>
  apiGet<PortalHints>('/asset/workspace/portal-hints')
export const reportRepairFromWorkspace = (assetId: number, description?: string): Promise<{
  repair_order_id: number; doc_no: string; created: boolean; note: string
}> => apiPost(`/asset/workspace/my-assets/${assetId}/report-repair`, { description: description ?? '' })
export const listMyReminders = (params?: { kind?: string; is_read?: boolean }): Promise<AssetReminder[]> => {
  const query = new URLSearchParams()
  if (params?.kind) query.set('kind', params.kind)
  if (params?.is_read !== undefined) query.set('is_read', String(params.is_read))
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return apiGet<AssetReminder[]>(`/asset/workspace/reminders${suffix}`)
}
export const markReminderRead = (id: number): Promise<AssetReminder> =>
  apiPost<AssetReminder>(`/asset/workspace/reminders/${id}/read`)
export const getAssetTimeline = (assetId: number): Promise<TimelineEntry[]> =>
  apiGet<TimelineEntry[]>(`/asset/assets/${assetId}/timeline`)
export const scanWarranty = (): Promise<{ reminded: number[]; window_days: number }> =>
  apiPost('/asset/workspace/scan-warranty')
export const scanApprovalOverdue = (): Promise<{ marked: number[]; reminded_instances: number[] }> =>
  apiPost('/asset/workspace/scan-approval-overdue')

/** 第 5 批:处置与报废(M8 #54~#58)。 */
export const DISPOSAL_TYPES = [
  { value: 'scrap', label: '报废' },
  { value: 'damage', label: '报损' },
  { value: 'loss_compensation', label: '丢失赔偿' },
  { value: 'free_transfer', label: '无偿划转' },
  { value: 'sale', label: '出售出让' },
  { value: 'exchange', label: '置换' },
  { value: 'donation_out', label: '捐赠转出' },
] as const

export interface DisposalOrder {
  id: number
  doc_no: string
  asset_id: number
  disposal_type: string
  reason: string
  materials: string[]
  materials_required: string[]
  status_before: string | null
  status: string
  approval_instance_id: number | null
  selected_for_official: boolean
  official_reply_no: string | null
  official_reply_at: string | null
  created_at: string | null
}

export interface DisposalAppraisal {
  id: number
  doc_no: string
  disposal_id: number
  inspector_name: string
  conclusion: string
  detail: string
  appraised_at: string | null
}

export interface DisposalPackage {
  id: number
  package_no: string
  disposal_id: number
  asset_count: number
  total_value: number | null
  status: string
  generated_at: string | null
}

export interface DisposalRecovery {
  id: number
  recovery_no: string
  disposal_id: number
  recovery_org: string
  residual_income: number | null
  voucher_no: string | null
  photo_urls: string[]
  status: string
  handover_at: string | null
}

/** 按处置类型取应交材料清单(#54)。 */
export const listDisposalMaterials = (disposalType: string): Promise<{
  disposal_type: string; label: string; materials_required: string[]
}> => apiGet(`/asset/disposals/materials?disposal_type=${encodeURIComponent(disposalType)}`)

/** 创建处置申请(#54):资产须已转入待处置,缺材料不得提交。 */
export const createDisposal = (body: {
  asset_id: number; disposal_type: string; reason?: string; materials: string[]
}): Promise<DisposalOrder> => apiPost<DisposalOrder>('/asset/disposals', body)
export const listDisposals = (params?: { status?: string; disposal_type?: string }): Promise<DisposalOrder[]> => {
  const query = new URLSearchParams()
  if (params?.status) query.set('status', params.status)
  if (params?.disposal_type) query.set('disposal_type', params.disposal_type)
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return apiGet<DisposalOrder[]>(`/asset/disposals${suffix}`)
}
export const getDisposal = (id: number): Promise<DisposalOrder> =>
  apiGet<DisposalOrder>(`/asset/disposals/${id}`)

/** 处置前技术鉴定(#55):鉴定人员填写,结论可继续使用则处置单关闭。 */
export const appraiseDisposal = (id: number, body: {
  conclusion: string; detail?: string
}): Promise<DisposalAppraisal> =>
  apiPost<DisposalAppraisal>(`/asset/disposals/${id}/appraise`, body)

/** 提交分级处置审批(#56):金额取资产原值。 */
export const submitDisposalApproval = (id: number): Promise<DisposalOrder> =>
  apiPost<DisposalOrder>(`/asset/disposals/${id}/submit-approval`)

/** 手动选择生成官方申报材料包(#57/#99)。 */
export const selectDisposalOfficial = (id: number): Promise<DisposalOrder> =>
  apiPost<DisposalOrder>(`/asset/disposals/${id}/select-official`)
export const createDisposalPackage = (id: number): Promise<DisposalPackage> =>
  apiPost<DisposalPackage>(`/asset/disposals/${id}/package`)
export const disposalPackageExportUrl = (id: number): string =>
  `/api/asset/disposals/${id}/package/export`

/** 官方批复回填(#57/#58)与手动确认核销(#58)。 */
export const recordDisposalReply = (id: number, replyNo: string): Promise<DisposalOrder> =>
  apiPost<DisposalOrder>(`/asset/disposals/${id}/official-reply`, { reply_no: replyNo })
export const confirmDisposalRetire = (id: number): Promise<DisposalOrder> =>
  apiPost<DisposalOrder>(`/asset/disposals/${id}/retire-confirm`)

/** 回收交接单(#58)。 */
export const getDisposalRecovery = (id: number): Promise<DisposalRecovery> =>
  apiGet<DisposalRecovery>(`/asset/disposals/${id}/recovery`)
export const completeDisposalRecovery = (id: number, body: {
  recovery_org: string; residual_income?: number | null; voucher_no?: string; photo_urls?: string[]
}): Promise<DisposalRecovery> =>
  apiPost<DisposalRecovery>(`/asset/disposals/${id}/recovery`, body)

/** 第 5 批:同步执行(M13 #91~#104/#106)与财务衔接(M15 #116)。 */
export interface SyncValidateResult {
  passed: number[]
  blocked: { asset_id: number; asset_code: string; missing: string[]; reasons: string[] }[]
  total: number
}
export interface SyncBatchItem {
  id: number
  asset_id: number
  asset_code: string
  status: string
  fail_reason: string
  official_code: string | null
}
export interface SyncBatch {
  id: number
  batch_no: string
  selection_batch_no: string | null
  status: string
  total_count: number
  total_value: number | null
  blocked_count: number
  items: SyncBatchItem[]
  blocked: SyncValidateResult['blocked']
  created_at: string | null
}
export interface SyncLog {
  id: number
  action: string
  batch_no: string | null
  asset_id: number | null
  asset_code: string | null
  operator_id: number | null
  operator_name: string
  result: string
  detail: string
  created_at: string | null
}
export interface PendingChange {
  asset_id: number
  asset_code: string
  name: string
  sync_status: string
  pending_sync_change_reason: string | null
}
export interface UnsyncedStat {
  category_code: string
  count: number
  total_value: number
}
export interface SyncBoundary {
  live_api: boolean
  adapter: string
  template_version: string
  boundary_note: string
  execution_note: string
  mapping_count: number
}
export interface ReconciliationCategory {
  category_code: string
  synced_count: number
  synced_original_value: number
  synced_net_value: number
  all_count: number
  all_original_value: number
  all_accumulated_depreciation: number
  all_net_value: number
}
export interface ReconciliationDiff {
  asset_id: number
  asset_code: string
  name: string
  category_code: string
  sync_status: string
  voucher_no: string | null
  original_value: number | null
  accumulated_depreciation: number | null
  net_value: number | null
  expected_net_value: number | null
  reason: string
}
export interface Reconciliation {
  month: string
  categories: ReconciliationCategory[]
  differences: ReconciliationDiff[]
  note: string
}

/** 同步前校验(#91)。 */
export const validateSync = (params?: { selection_batch_no?: string }): Promise<SyncValidateResult> => {
  const suffix = params?.selection_batch_no
    ? `?selection_batch_no=${encodeURIComponent(params.selection_batch_no)}` : ''
  return apiGet<SyncValidateResult>(`/asset/sync/validate${suffix}`)
}

/** 生成同步批次(#92/#94):须二次确认 confirm=true,显示件数与总价值。 */
export const createSyncBatch = (body: {
  selection_batch_no?: string; asset_ids?: number[]; confirm: boolean
}): Promise<SyncBatch> => apiPost<SyncBatch>('/asset/sync/batches', body)
export const listSyncBatches = (): Promise<SyncBatch[]> =>
  apiGet<SyncBatch[]>('/asset/sync/batches')
export const syncBatchExportUrl = (batchId: number): string =>
  `/api/asset/sync/batches/${batchId}/export`

/** 官方编号批量回填(#96)与结果确认(#97)。 */
export const backfillOfficialCodes = (batchId: number, items: {
  asset_id: number; official_code: string
}[]): Promise<{ asset_id: number; asset_code: string | null; ok: boolean; reason: string; official_code: string | null }[]> =>
  apiPost(`/asset/sync/batches/${batchId}/backfill`, { items })
export const confirmSyncBatch = (batchId: number, results: {
  asset_id: number; ok: boolean; reason?: string
}[]): Promise<SyncBatch> =>
  apiPost<SyncBatch>(`/asset/sync/batches/${batchId}/confirm`, { results })

/** 待同步变更清单(#98)与未同步资产单独统计(#100)。 */
export const listPendingSyncChanges = (): Promise<PendingChange[]> =>
  apiGet<PendingChange[]>('/asset/sync/pending-changes')
export const listUnsyncedStats = (): Promise<UnsyncedStat[]> =>
  apiGet<UnsyncedStat[]>('/asset/sync/unsynced-stats')

/** 同步日志(#102,只读)与积压提醒(#103,只提醒不执行)。 */
export const listSyncLogs = (params?: { batch_no?: string }): Promise<SyncLog[]> => {
  const suffix = params?.batch_no ? `?batch_no=${encodeURIComponent(params.batch_no)}` : ''
  return apiGet<SyncLog[]>(`/asset/sync/logs${suffix}`)
}
export const scanSyncBacklog = (): Promise<{
  reminded_batches: string[]; asset_count: number; threshold_days: number
}> => apiPost('/asset/sync/scan-backlog')

/** 对接边界说明(#106)。 */
export const getSyncBoundary = (): Promise<SyncBoundary> =>
  apiGet<SyncBoundary>('/asset/sync/boundary')

/** 月度对账清单(#116,只读)。 */
export const getReconciliation = (month: string): Promise<Reconciliation> =>
  apiGet<Reconciliation>(`/asset/finance/reconciliation?month=${encodeURIComponent(month)}`)
export const reconciliationExportUrl = (month: string): string =>
  `/api/asset/finance/reconciliation/export?month=${encodeURIComponent(month)}`
