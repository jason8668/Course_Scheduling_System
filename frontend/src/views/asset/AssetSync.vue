<script setup lang="ts">
import {
  NAlert, NButton, NDataTable, NInput, NSelect, NSpace,
} from 'naive-ui'
import { computed, h, onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import {
  backfillOfficialCodes, createSyncBatch, getReconciliation,
  getSyncBoundary, listPendingSyncChanges, listSyncBatches, listSyncLogs,
  listUnsyncedStats, scanSyncBacklog, syncBatchExportUrl, validateSync,
} from '@/api/asset'
import { getSyncPool } from '@/api/asset'
import type {
  PendingChange, Reconciliation, SyncBatch, SyncBoundary, SyncLog, SyncPool,
  UnsyncedStat,
} from '@/api/asset'
import AssetPicker from '@/components/AssetPicker.vue'

// 学校资产管理系统一期第 5 批:对接与同步(M13 #91~#104/#106)与财务衔接(M15 #116)。
// 待同步池 → 校验 → 批次 → 二次确认 → 导出 → 回填 → 结果确认 + 同步日志 +
// 未同步统计。
// 一期为模板交换,实时接口未开放。

const loading = ref(false)
const boundary = ref<SyncBoundary | null>(null)
const pool = ref<SyncPool>({ items: [], total: 0, total_value: 0, groups: {} })
const validateResult = ref('')
const confirmChecked = ref(false)
const batches = ref<SyncBatch[]>([])
const pendingChanges = ref<PendingChange[]>([])
const unsyncedStats = ref<UnsyncedStat[]>([])
const logs = ref<SyncLog[]>([])
const reconciliation = ref<Reconciliation | null>(null)
const resultMsg = ref('')
const errorMsg = ref('')
const backfillBatchId = ref('')
const backfillAssetId = ref<number | null>(null)
const backfillCode = ref('')
const exportBatchId = ref<number | null>(null)
const month = ref('2026-11')

const batchOptions = computed(() => batches.value.map((b) => ({
  label: `${b.batch_no}(${b.total_count} 件)`,
  value: b.id,
})))

function pickBatch(row: SyncBatch) {
  backfillBatchId.value = String(row.id)
  exportBatchId.value = row.id
  resultMsg.value = `已选中同步批次 ${row.batch_no},回填与导出都针对该批次`
  errorMsg.value = ''
}

function doExportBatch() {
  if (!exportBatchId.value) {
    errorMsg.value = '请先在上方选择要导出的同步批次'
    resultMsg.value = ''
    return
  }
  window.open(syncBatchExportUrl(exportBatchId.value), '_blank')
}

async function load() {
  loading.value = true
  errorMsg.value = ''
  try {
    boundary.value = await getSyncBoundary()
    pool.value = await getSyncPool()
    batches.value = await listSyncBatches()
    pendingChanges.value = await listPendingSyncChanges()
    unsyncedStats.value = await listUnsyncedStats()
    logs.value = await listSyncLogs()
  } catch (e) {
    errorMsg.value = (e as ApiError).message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function doValidate() {
  try {
    const data = await validateSync()
    validateResult.value = `校验:${data.total} 件,通过 ${data.passed.length} 件,`
      + `拦截 ${data.blocked.length} 件`
      + (data.blocked.length
        ? `;拦截原因:${data.blocked.map((b) => `${b.asset_code}:${b.reasons.join('、')}`).join('；')}` : '')
  } catch (e) {
    errorMsg.value = (e as ApiError).message || '校验失败'
  }
}

async function doCreateBatch() {
  if (!confirmChecked.value) {
    errorMsg.value = '同步执行须二次确认:请先勾选确认本次件数与总价值'
    return
  }
  try {
    const batch = await createSyncBatch({ confirm: true })
    resultMsg.value = `同步批次已生成:${batch.batch_no} ${batch.total_count} 件,`
      + `总价值 ${batch.total_value ?? 0} 元,拦截 ${batch.blocked_count} 件留池`
    await load()
  } catch (e) {
    errorMsg.value = (e as ApiError).message || '生成批次失败'
  }
}

async function doBackfill() {
  if (!backfillBatchId.value || !backfillAssetId.value || !backfillCode.value) {
    errorMsg.value = '请先选中同步批次和资产,并填写官方编号'
    return
  }
  try {
    const results = await backfillOfficialCodes(Number(backfillBatchId.value), [
      { asset_id: Number(backfillAssetId.value), official_code: backfillCode.value },
    ])
    const item = results[0]
    resultMsg.value = item.ok
      ? `回填成功:${item.official_code},双号索引已建立`
      : `回填失败:${item.reason}`
    await load()
  } catch (e) {
    errorMsg.value = (e as ApiError).message || '回填失败'
  }
}

async function doScanBacklog() {
  try {
    const data = await scanSyncBacklog()
    resultMsg.value = `积压提醒已发送:${data.reminded_batches.length} 个批次,`
      + `${data.asset_count} 件(只提醒,不自动执行同步)`
    await load()
  } catch (e) {
    errorMsg.value = (e as ApiError).message || '扫描失败'
  }
}

async function doReconciliation() {
  try {
    reconciliation.value = await getReconciliation(month.value)
  } catch (e) {
    errorMsg.value = (e as ApiError).message || '对账清单加载失败'
  }
}

onMounted(load)
</script>

<template>
  <div class="ios-page">
    <h1 class="ios-title">同步执行与对账</h1>
    <NAlert v-if="boundary" type="warning" style="margin-bottom: 12px">
      {{ boundary.execution_note }}(模板版本:{{ boundary.template_version }})
    </NAlert>
    <NAlert type="info" style="margin-bottom: 12px">
      同步四步:第 1 步点“同步前校验”,拦截的不合格资产会留在池里 → 第 2 步勾选确认本次件数与总价值,点“生成同步批次” →
      第 3 步选批次导出官方模板,按模板报送 → 第 4 步官方编号下来后,在下方按批次回填,资产变“已同步”。
      只有待同步池里勾选的资产才会同步,入库默认未同步,不会自动上报。
    </NAlert>
    <NAlert v-if="errorMsg" type="error" style="margin-bottom: 12px">{{ errorMsg }}</NAlert>
    <NAlert v-if="resultMsg" type="success" style="margin-bottom: 12px">{{ resultMsg }}</NAlert>
    <div class="ios-card" style="margin-top: 16px">
      <div class="ios-card-body">

    <p>待同步池:共 {{ pool.total }} 件,总价值 {{ pool.total_value }} 元</p>
    <NSpace>
      <NButton @click="doValidate">同步前校验</NButton>
      <label><input v-model="confirmChecked" type="checkbox"> 我已核对本次件数与总价值,确认执行同步</label>
      <NButton type="primary" @click="doCreateBatch">生成同步批次</NButton>
      <NButton @click="doScanBacklog">积压提醒扫描</NButton>
    </NSpace>
    <p v-if="validateResult">{{ validateResult }}</p>

    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 0px">同步批次</div>
    <p>点“选中回填”可把批次号填入下方回填框;导出模板请在下方选批次再点导出。</p>
    <NDataTable :bordered="false" :single-line="false"
      :columns="[
        { title: '同步批次号', key: 'batch_no', width: 180 },
        { title: '勾选批次', key: 'selection_batch_no', width: 180 },
        { title: '状态', key: 'status', width: 100 },
        { title: '件数', key: 'total_count', width: 80 },
        { title: '总价值(元)', key: 'total_value', width: 120 },
        { title: '拦截件数', key: 'blocked_count', width: 100 },
        {
          title: '回填', key: 'pick', width: 110,
          render: (r: SyncBatch) => h(
            NButton, { size: 'small', onClick: () => pickBatch(r) }, () => '选中回填',
          ),
        },
      ]"
      :data="batches" :loading="loading" :row-key="(r: SyncBatch) => r.id"
    />
    <NSpace style="margin-top: 8px">
      <NInput v-model:value="backfillBatchId" placeholder="批次 ID" style="width: 120px" />
      <AssetPicker v-model="backfillAssetId" style="width: 280px" />
      <NInput v-model:value="backfillCode" placeholder="官方编号" style="width: 160px" />
      <NButton @click="doBackfill">编号回填</NButton>
    </NSpace>
    <NSpace style="margin-top: 8px">
      <NSelect
        v-model:value="exportBatchId" :options="batchOptions" filterable clearable
        placeholder="选择要导出的同步批次" style="width: 280px"
      />
      <NButton :disabled="!exportBatchId" @click="doExportBatch">导出选中批次模板</NButton>
    </NSpace>

    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20px">待同步变更</div>
    <p v-if="pendingChanges.length === 0">暂无待同步变更</p>
    <NDataTable :bordered="false" :single-line="false"
      v-else
      :columns="[
        { title: '资产编号', key: 'asset_code', width: 160 },
        { title: '名称', key: 'name' },
        { title: '变更原因', key: 'pending_sync_change_reason' },
      ]"
      :data="pendingChanges" :row-key="(r: PendingChange) => r.asset_id"
    />

    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20px">未同步资产统计(校内口径)</div>
    <NDataTable :bordered="false" :single-line="false"
      :columns="[
        { title: '分类代码', key: 'category_code', width: 120 },
        { title: '件数', key: 'count', width: 90 },
        { title: '总价值(元)', key: 'total_value', width: 140 },
      ]"
      :data="unsyncedStats" :row-key="(r: UnsyncedStat) => r.category_code"
    />

    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20px">同步日志</div>
    <NDataTable :bordered="false" :single-line="false"
      :columns="[
        { title: '动作', key: 'action', width: 140 },
        { title: '批次号', key: 'batch_no', width: 180 },
        { title: '资产编号', key: 'asset_code', width: 160 },
        { title: '操作人', key: 'operator_name', width: 100 },
        { title: '结果', key: 'result', width: 90 },
        { title: '说明', key: 'detail' },
      ]"
      :data="logs" :row-key="(r: SyncLog) => r.id"
    />

    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20px">月度对账清单</div>
    <NSpace>
      <NInput v-model:value="month" placeholder="YYYY-MM" style="width: 120px" />
      <NButton @click="doReconciliation">生成对账清单</NButton>
    </NSpace>
    <p v-if="reconciliation">{{ reconciliation.note }}</p>
    <NDataTable :bordered="false" :single-line="false"
      v-if="reconciliation"
      :columns="[
        { title: '分类', key: 'category_code', width: 110 },
        { title: '已同步件数', key: 'synced_count', width: 110 },
        { title: '已同步原值', key: 'synced_original_value', width: 120 },
        { title: '校内件数', key: 'all_count', width: 100 },
        { title: '校内原值', key: 'all_original_value', width: 120 },
      ]"
      :data="reconciliation.categories" :row-key="(r) => r.category_code"
    />
    <p v-if="reconciliation && reconciliation.differences.length">
      差异 {{ reconciliation.differences.length }} 条:
      {{ reconciliation.differences.map((d) => `${d.asset_code}:${d.reason}`).join('；') }}
    </p>
      </div>
    </div>
  </div>
</template>
