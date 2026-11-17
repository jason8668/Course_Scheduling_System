<script setup lang="ts">
import {
  NAlert, NButton, NDataTable, NInput, NPopconfirm, NSelect, NSpace,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { h, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import { apiGet } from '@/api/client'
import {
  assetExportUrl, bulkUpdateAssets, listIdleAssets, refreshIdleAssets,
  searchAssets, selectForSync,
} from '@/api/asset'
import type { AssetCard, AssetIdle } from '@/api/asset'

// 学校资产管理系统一期第 2 批:资产台账(#8/#9/#13/#14/#87/#88)。
// 多维组合查询 + 导出 + 批量维护 + 闲置清单 + 勾选同步。
// 导出用浏览器直接打开下载地址。

const router = useRouter()

const loading = ref(false)
const forbidden = ref(false)
const rows = ref<AssetCard[]>([])
const total = ref(0)
const checkedKeys = ref<number[]>([])
const resultMsg = ref('')
const idleRows = ref<AssetIdle[]>([])

const categoryFilter = ref('')
const deptFilter = ref('')
const custodianFilter = ref('')
const statusFilter = ref('')
const syncFilter = ref('')
const minValue = ref('')
const maxValue = ref('')
const keyword = ref('')
const newCustodian = ref('')

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '在库', value: '在库' },
  { label: '在用', value: '在用' },
  { label: '借出', value: '借出' },
  { label: '维修中', value: '维修中' },
  { label: '待处置', value: '待处置' },
  { label: '已核销', value: '已核销' },
]
const syncOptions = [
  { label: '全部同步状态', value: '' },
  { label: '未同步', value: '未同步' },
  { label: '待同步', value: '待同步' },
  { label: '同步中', value: '同步中' },
  { label: '已同步', value: '已同步' },
  { label: '同步失败', value: '同步失败' },
  { label: '已取消同步', value: '已取消同步' },
]
// 部门筛选改下拉(#76):口径走部门字典,不再手填自由文本。
const deptOptions = ref([{ label: '全部部门', value: '' }])

async function loadDepts() {
  try {
    const depts = await apiGet<Array<{ name: string }>>('/asset/departments?is_active=true')
    deptOptions.value = [
      { label: '全部部门', value: '' },
      ...depts.map((d) => ({ label: d.name, value: d.name })),
    ]
  } catch {
    deptOptions.value = [{ label: '全部部门', value: '' }]
  }
}

const columns: DataTableColumns<AssetCard> = [
  { type: 'selection', width: 40 },
  {
    title: '资产编号', key: 'asset_code', width: 150,
    render: (r: AssetCard) => h(
      NButton,
      { text: true, type: 'primary', onClick: () => openCard(r) },
      () => r.asset_code,
    ),
  },
  { title: '名称', key: 'name' },
  { title: '分类', key: 'category_code', width: 100 },
  { title: '原值(元)', key: 'original_value', width: 100 },
  { title: '管理部门', key: 'manage_dept', width: 100 },
  { title: '保管人', key: 'custodian_name', width: 90 },
  { title: '状态', key: 'status', width: 80 },
  { title: '同步状态', key: 'sync_status', width: 90 },
  { title: '是否入账', key: 'is_booked', width: 90, render: (r: AssetCard) => (r.is_booked ? '已入账' : '未入账') },
  { title: '闲置', key: 'is_idle', width: 70, render: (r: AssetCard) => (r.is_idle ? '闲置' : '—') },
]

function onChecked(keys: Array<string | number>) {
  checkedKeys.value = keys.map((k) => Number(k))
}

function openCard(row: AssetCard) {
  router.push({ name: 'asset-card', query: { id: String(row.id) } })
}

function goIntake() {
  router.push({ name: 'asset-intake' })
}

function filters() {
  return {
    category_code: categoryFilter.value || undefined,
    manage_dept: deptFilter.value || undefined,
    custodian_name: custodianFilter.value || undefined,
    status: statusFilter.value || undefined,
    sync_status: syncFilter.value || undefined,
    min_value: minValue.value ? Number(minValue.value) : undefined,
    max_value: maxValue.value ? Number(maxValue.value) : undefined,
    q: keyword.value || undefined,
  }
}

async function load() {
  loading.value = true
  forbidden.value = false
  try {
    const data = await searchAssets(filters())
    rows.value = data.items
    total.value = data.total
  } catch (e) {
    if ((e as ApiError).status === 403) forbidden.value = true
  } finally {
    loading.value = false
  }
}

function doExport(includeExt: boolean) {
  window.open(assetExportUrl(filters(), includeExt), '_blank')
}

async function doBulkCustodian() {
  if (!newCustodian.value || checkedKeys.value.length === 0) return
  const res = await bulkUpdateAssets({
    asset_ids: checkedKeys.value, custodian_name: newCustodian.value,
  })
  resultMsg.value = `批量改保管人:成功 ${res.succeeded.length} 件,失败 ${res.failed.length} 件`
    + (res.failed.length ? `(${res.failed.map((f) => f.reason).join('；')})` : '')
  await load()
}

async function doSelectSync() {
  if (checkedKeys.value.length === 0) return
  const res = await selectForSync(checkedKeys.value)
  resultMsg.value = `勾选同步:成功 ${res.succeeded.length} 件,失败 ${res.failed.length} 件`
    + (res.failed.length ? `(${res.failed.map((f) => f.reason).join('；')})` : '')
  await load()
}

async function loadIdle() {
  idleRows.value = await listIdleAssets()
}

async function doRefreshIdle() {
  const res = await refreshIdleAssets()
  resultMsg.value = `闲置识别刷新:阈值 ${res.threshold_days} 天,闲置 ${res.idle_count} 件`
  await loadIdle()
  await load()
}

onMounted(() => { load(); loadIdle(); loadDepts() })
</script>

<template>
  <div class="ios-page">
    <h1 class="ios-title">资产台账</h1>
    <NAlert type="info" style="margin-bottom: 12px">
      多维组合查询:按分类、部门、保管人、状态、价值区间、同步状态等组合定位资产;
      导出默认只含校内台账字段,扩展区字段须勾选才导出。
    </NAlert>
    <NAlert v-if="forbidden" type="error" style="margin-bottom: 12px">权限不足</NAlert>
    <NAlert v-if="!loading && !forbidden && rows.length === 0" type="info" style="margin-bottom: 12px">
      台账还是空的:先去“入库验收”新建验收单、验收通过后建卡,卡建好就会出现在这里。
      <NButton size="small" type="primary" style="margin-left: 8px" @click="goIntake">去入库验收</NButton>
    </NAlert>
    <div class="ios-card" style="margin-top: 16px">
      <div class="ios-card-body">
    <NSpace style="margin-bottom: 12px" vertical>
      <NSpace>
        <NInput v-model:value="categoryFilter" placeholder="分类代码(如 A0203)" style="width: 180px" />
        <NSelect v-model:value="deptFilter" :options="deptOptions" placeholder="管理部门" style="width: 140px" />
        <NInput v-model:value="custodianFilter" placeholder="保管人" style="width: 120px" />
        <NInput v-model:value="keyword" placeholder="名称/编号关键词" style="width: 180px" />
        <NInput v-model:value="minValue" placeholder="原值下限" style="width: 110px" />
        <NInput v-model:value="maxValue" placeholder="原值上限" style="width: 110px" />
      </NSpace>
      <NSpace>
        <NSelect v-model:value="statusFilter" :options="statusOptions" style="width: 140px" />
        <NSelect v-model:value="syncFilter" :options="syncOptions" style="width: 160px" />
        <NButton type="primary" :loading="loading" @click="load">查询</NButton>
        <!-- 第 6 批 #84:导出全量数据二次确认(导出动作后端记审计 asset_ledger_export)。 -->
        <NPopconfirm @positive-click="doExport(false)">
          <template #trigger><NButton>导出 Excel</NButton></template>
          确认导出当前筛选结果共 {{ total }} 件资产的台账数据吗?
        </NPopconfirm>
        <NPopconfirm @positive-click="doExport(true)">
          <template #trigger><NButton>导出 Excel(含扩展区)</NButton></template>
          确认导出当前筛选结果共 {{ total }} 件资产的台账数据(含校内扩展区字段)吗?
        </NPopconfirm>
        <NButton @click="doRefreshIdle">刷新闲置识别</NButton>
      </NSpace>
      <NSpace>
        <NInput v-model:value="newCustodian" placeholder="批量改保管人为" style="width: 160px" />
        <NButton :disabled="checkedKeys.length === 0" @click="doBulkCustodian">批量改保管人</NButton>
        <NButton type="primary" :disabled="checkedKeys.length === 0" @click="doSelectSync">勾选同步</NButton>
        <span>共 {{ total }} 件,已选 {{ checkedKeys.length }} 件</span>
      </NSpace>
    </NSpace>
    <NAlert v-if="resultMsg" type="success" style="margin-bottom: 12px">{{ resultMsg }}</NAlert>
    <p>点资产编号可打开该资产的资产卡;勾选多行可批量改保管人或勾选同步。</p>
    <NDataTable :bordered="false" :single-line="false"
      :columns="columns" :data="rows" :loading="loading" :row-key="(r: AssetCard) => r.id"
      :checked-row-keys="checkedKeys" @update:checked-row-keys="onChecked"
    />
    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20px">闲置清单</div>
    <p v-if="idleRows.length === 0">暂无闲置资产(闲置标记由刷新任务计算,不手工打标记)。</p>
    <NDataTable :bordered="false" :single-line="false"
      v-else
      :columns="[
        { title: '资产编号', key: 'asset_code' },
        { title: '名称', key: 'name' },
        { title: '分类', key: 'category_code' },
        { title: '保管人', key: 'custodian_name' },
        { title: '闲置原因', key: 'idle_reason' },
      ]"
      :data="idleRows" :row-key="(r: AssetIdle) => r.id"
    />
      </div>
    </div>
  </div>
</template>
