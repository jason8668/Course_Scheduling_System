<script setup lang="ts">
import {
  NAlert, NButton, NInput, NSpace,
} from 'naive-ui'
import { ref } from 'vue'
import type { ApiError } from '@/api/client'
import {
  confirmIssueScan, scanInventory, scanRepair, searchAssets,
} from '@/api/asset'
import type { AssetCard, RepairScanResult } from '@/api/asset'

// 学校资产管理系统一期第 6 批:移动端四件事(#113)。
// 手机端只做扫码查卡、扫码报修、借用/领用确认、盘点作业,界面极简;
// 全部复用已有接口,不新建后端逻辑、不做移动端 App。
// 扫码入口集中在每项顶部的大输入框(扫码枪/手机扫码键盘回填后点大按钮)。
// 查卡用台账组合查询(#8)的 q 关键词;报修用扫码报修(#42);
// 确认用领用扫码确认(#31);盘点用手机扫码盘点(#49)。
// 未接路由(由收尾批统一接线,见 portal-wiring-patch.md)。

type Tab = 'lookup' | 'repair' | 'confirm' | 'inventory'
const tab = ref<Tab>('lookup')
const tabs: { key: Tab; label: string }[] = [
  { key: 'lookup', label: '扫码查卡' },
  { key: 'repair', label: '扫码报修' },
  { key: 'confirm', label: '借用/领用确认' },
  { key: 'inventory', label: '盘点作业' },
]

const loading = ref(false)
const resultMsg = ref('')
const errorMsg = ref('')

function reset() {
  resultMsg.value = ''
  errorMsg.value = ''
}

function fail(e: unknown) {
  errorMsg.value = (e as ApiError).message || '操作失败'
}

// ── 扫码查卡 ──
const lookupCode = ref('')
const card = ref<AssetCard | null>(null)

async function doLookup() {
  if (!lookupCode.value) return
  reset()
  card.value = null
  loading.value = true
  try {
    const data = await searchAssets({ q: lookupCode.value })
    if (data.items.length === 0) {
      errorMsg.value = '未找到该编号/名称的资产'
      return
    }
    card.value = data.items[0]
    resultMsg.value = `找到 ${data.total} 件,显示第 1 件`
  } catch (e) {
    fail(e)
  } finally {
    loading.value = false
  }
}

// ── 扫码报修 ──
const repairCode = ref('')
const repairDesc = ref('')
const repairResult = ref<RepairScanResult | null>(null)

async function doRepairScan() {
  if (!repairCode.value) return
  reset()
  repairResult.value = null
  loading.value = true
  try {
    repairResult.value = await scanRepair({
      label_code: repairCode.value, description: repairDesc.value || undefined,
    })
    resultMsg.value = repairResult.value.created ? '已生成维修单' : '已找到在修工单'
  } catch (e) {
    fail(e)
  } finally {
    loading.value = false
  }
}

// ── 借用/领用确认 ──
const confirmOrderId = ref('')
const confirmCode = ref('')

async function doConfirm() {
  if (!confirmOrderId.value || !confirmCode.value) return
  reset()
  loading.value = true
  try {
    const order = await confirmIssueScan(Number(confirmOrderId.value), confirmCode.value)
    resultMsg.value = `领用单 ${order.doc_no} 已确认接收,资产转为在用`
  } catch (e) {
    fail(e)
  } finally {
    loading.value = false
  }
}

// ── 盘点作业:离线暂存、弱网续传(#49,复核补) ──
const inventoryTaskId = ref('')
const inventoryCode = ref('')
// 此前只把 is_offline 标志传给同一在线接口,断网时根本调不通接口,
// 谈不上离线暂存。现补本地发件箱:网络异常(无 HTTP 状态的抛错,
// 即 fetch 本身失败)时把本次扫码存入 localStorage,联网后点
// “重新同步”逐条补传(is_offline=true);业务报错(有 HTTP 状态,
// 如任务不存在)不暂存,直接显示错误。
const OFFLINE_KEY = 'asset-offline-inventory-scans'
interface OfflineScan { task_id: number; label_code: string; saved_at: string }
function loadOfflineScans(): OfflineScan[] {
  try {
    const raw = localStorage.getItem(OFFLINE_KEY)
    const list = raw ? JSON.parse(raw) as OfflineScan[] : []
    return Array.isArray(list) ? list : []
  } catch {
    return []
  }
}
const offlinePending = ref<OfflineScan[]>(loadOfflineScans())
function saveOfflineScans(list: OfflineScan[]) {
  offlinePending.value = list
  try {
    if (list.length === 0) localStorage.removeItem(OFFLINE_KEY)
    else localStorage.setItem(OFFLINE_KEY, JSON.stringify(list))
  } catch {
    // 存储不可用时仅保留内存态,不阻塞盘点。
  }
}

async function resyncOffline() {
  const pending = loadOfflineScans()
  if (pending.length === 0) return
  reset()
  loading.value = true
  let ok = 0
  const remain: OfflineScan[] = []
  for (const item of pending) {
    try {
      await scanInventory(item.task_id, { label_code: item.label_code, is_offline: true })
      ok += 1
    } catch {
      remain.push(item)
    }
  }
  saveOfflineScans(remain)
  resultMsg.value = remain.length === 0
    ? `已补传 ${ok} 条离线盘点记录`
    : `已补传 ${ok} 条,仍有 ${remain.length} 条未成功,请稍后重试`
  loading.value = false
}

async function doInventoryScan() {
  if (!inventoryTaskId.value || !inventoryCode.value) return
  reset()
  loading.value = true
  try {
    const res = await scanInventory(Number(inventoryTaskId.value), {
      label_code: inventoryCode.value,
    })
    resultMsg.value = res.message
    if (!res.in_scope) errorMsg.value = '该资产不在本次盘点范围内,未计入'
  } catch (e) {
    if ((e as ApiError).status === undefined) {
      // 无 HTTP 响应:断网/弱网,离线暂存而非丢弃。
      const list = loadOfflineScans()
      list.push({
        task_id: Number(inventoryTaskId.value),
        label_code: inventoryCode.value,
        saved_at: new Date().toISOString(),
      })
      saveOfflineScans(list)
      resultMsg.value = '网络异常，已离线暂存，联网后点“重新同步”补传'
    } else {
      fail(e)
    }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="ios-page asset-mobile">
    <h1 class="ios-title">资产移动端</h1>
    <NAlert type="info" style="margin-bottom: 12px">
      手机端只做四件事:扫码查卡、扫码报修、借用/领用确认、盘点作业。
      同步执行、审批、处置等请在电脑端办理。
    </NAlert>
    <div class="ios-card" style="margin-top: 16px">
      <div class="ios-card-body">
    <NSpace vertical>
      <NButton
        v-for="t in tabs" :key="t.key"
        :type="tab === t.key ? 'primary' : 'default'"
        size="large" block
        @click="tab = t.key; reset()"
      >
        {{ t.label }}
      </NButton>
    </NSpace>

    <div v-if="tab === 'lookup'" style="margin-top: 16px">
      <NInput
        v-model:value="lookupCode" placeholder="扫码或输入资产编号/名称"
        size="large" style="margin-bottom: 12px"
      />
      <NButton type="primary" size="large" block :loading="loading" @click="doLookup">查卡</NButton>
      <div v-if="card" style="margin-top: 16px">
        <p>名称:{{ card.name }}</p>
        <p>编号:{{ card.asset_code }}</p>
        <p>状态:{{ card.status }} · 保管人:{{ card.custodian_name ?? '—' }}</p>
        <p>存放:{{ card.room_name ?? '—' }} · 管理部门:{{ card.manage_dept ?? '—' }}</p>
        <p>原值:{{ card.original_value ?? '—' }} 元</p>
      </div>
    </div>

    <div v-if="tab === 'repair'" style="margin-top: 16px">
      <NInput
        v-model:value="repairCode" placeholder="扫码或输入标签码"
        size="large" style="margin-bottom: 12px"
      />
      <NInput
        v-model:value="repairDesc" placeholder="故障描述(可选)"
        size="large" style="margin-bottom: 12px"
      />
      <NButton type="primary" size="large" block :loading="loading" @click="doRepairScan">扫码报修</NButton>
      <div v-if="repairResult" style="margin-top: 16px">
        <p>设备:{{ repairResult.name }}({{ repairResult.asset_code }})</p>
        <p>存放:{{ repairResult.room_name ?? '—' }} · 状态:{{ repairResult.status }}</p>
        <p>{{ repairResult.warranty_hint }}</p>
        <p v-if="repairResult.doc_no">维修单:{{ repairResult.doc_no }}</p>
      </div>
    </div>

    <div v-if="tab === 'confirm'" style="margin-top: 16px">
      <NInput
        v-model:value="confirmOrderId" placeholder="领用单 id" inputmode="numeric"
        size="large" style="margin-bottom: 12px"
      />
      <NInput
        v-model:value="confirmCode" placeholder="扫码或输入标签码"
        size="large" style="margin-bottom: 12px"
      />
      <NButton type="primary" size="large" block :loading="loading" @click="doConfirm">确认接收</NButton>
    </div>

    <div v-if="tab === 'inventory'" style="margin-top: 16px">
      <NInput
        v-model:value="inventoryTaskId" placeholder="盘点任务 id" inputmode="numeric"
        size="large" style="margin-bottom: 12px"
      />
      <NInput
        v-model:value="inventoryCode" placeholder="扫码或输入标签码"
        size="large" style="margin-bottom: 12px"
      />
      <NButton type="primary" size="large" block :loading="loading" @click="doInventoryScan">扫码盘点</NButton>
      <p>断网时扫码会自动离线暂存，联网后点“重新同步”补传。</p>
      <div v-if="offlinePending.length > 0" style="margin-top: 12px">
        <p>待补传离线记录 {{ offlinePending.length }} 条</p>
        <NButton size="large" block :loading="loading" @click="resyncOffline">重新同步</NButton>
      </div>
    </div>

    <NAlert v-if="resultMsg" type="success" style="margin-top: 16px">{{ resultMsg }}</NAlert>
    <NAlert v-if="errorMsg" type="error" style="margin-top: 16px">{{ errorMsg }}</NAlert>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 移动端极简页:窄屏单列、大按钮,复用全局样式,不另写主题。 */
.asset-mobile { padding: 16px; max-width: 560px; margin: 0 auto; }
.asset-mobile p { margin: 6px 0; font-size: 15px; }
</style>
