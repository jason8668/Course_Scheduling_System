<script setup lang="ts">
import {
  NAlert, NButton, NCheckbox, NDataTable, NInput, NSpace,
} from 'naive-ui'
import { h, onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import {
  confirmRepair, dispatchRepair, getRepairCostSummary, listRepairs, recordRepair,
  scanRepair,
} from '@/api/asset'
import type { RepairCostSummary, RepairOrder, RepairScanResult } from '@/api/asset'
import AssetPicker from '@/components/AssetPicker.vue'

// 学校资产管理系统一期第 4 批:维修与保养(#42/#43/#44)。
// 保内故障在报修回显中明确提示走厂商保修;
// 费用 ≥5000 元(参数 approval.repair_threshold)登记后先入待审批,审批通过
// 才可由报修人确认关闭;维修记录经履历时间轴查看(AssetCard 页)。

const resultMsg = ref('')
const errorMsg = ref('')

const labelCode = ref('')
const description = ref('')
const photoUrl = ref('')
const scanResult = ref<RepairScanResult | null>(null)

const repairs = ref<RepairOrder[]>([])
const dispatchId = ref('')
const assigneeName = ref('')
const vendor = ref('')
const sendToRepair = ref(true)
const recordId = ref('')
const recordCost = ref('')
const recordResult = ref('')
const summaryAssetId = ref<number | null>(null)
const summary = ref<RepairCostSummary | null>(null)

async function load() {
  try {
    repairs.value = await listRepairs()
  } catch (e) {
    errorMsg.value = (e as ApiError).detail ?? '加载失败'
  }
}

function showError(e: unknown) {
  errorMsg.value = (e as ApiError).detail ?? '操作失败'
  resultMsg.value = ''
}

async function doScanRepair() {
  try {
    scanResult.value = await scanRepair({
      label_code: labelCode.value || undefined,
      description: description.value, photo_url: photoUrl.value || undefined,
    })
    resultMsg.value = scanResult.value.created
      ? `报修成功:${scanResult.value.doc_no}`
      : `已有未关闭维修单:${scanResult.value.doc_no}`
    errorMsg.value = ''
    await load()
  } catch (e) { showError(e) }
}

async function doDispatch() {
  try {
    const row = await dispatchRepair(Number(dispatchId.value), {
      assignee_name: assigneeName.value || undefined,
      vendor: vendor.value || undefined, send_to_repair: sendToRepair.value,
    })
    resultMsg.value = `维修单 ${row.doc_no} 当前状态:${row.status}`
    errorMsg.value = ''
    await load()
  } catch (e) { showError(e) }
}

async function doRecord() {
  try {
    const row = await recordRepair(Number(recordId.value), {
      vendor: vendor.value || undefined, cost: Number(recordCost.value),
      result: recordResult.value,
    })
    resultMsg.value = row.status === '待审批'
      ? `维修单 ${row.doc_no} 费用超阈值,已发起审批,审批通过后才可确认`
      : `维修单 ${row.doc_no} 已登记结果,待报修人确认`
    errorMsg.value = ''
    await load()
  } catch (e) { showError(e) }
}

async function doConfirm(id: number) {
  try {
    const row = await confirmRepair(id)
    resultMsg.value = `维修单 ${row.doc_no} 报修人已确认关闭,费用已累计`
    errorMsg.value = ''
    await load()
  } catch (e) { showError(e) }
}

async function doSummary() {
  if (!summaryAssetId.value) {
    errorMsg.value = '请先在上方搜索并选择资产'
    resultMsg.value = ''
    return
  }
  try {
    summary.value = await getRepairCostSummary(summaryAssetId.value)
    errorMsg.value = ''
  } catch (e) { showError(e) }
}

function pickRepair(row: RepairOrder) {
  dispatchId.value = String(row.id)
  recordId.value = String(row.id)
  resultMsg.value = `已选中维修单 ${row.doc_no},派单或登记结果时不用再填单号`
  errorMsg.value = ''
}

onMounted(load)
</script>

<template>
  <div class="ios-page">
    <h1 class="ios-title">维修与保养</h1>
    <NAlert type="info" style="margin-bottom: 12px">
      维修四步:扫标签码报修 → 管理员派单(可同时送修) → 登记维修方、费用、结果 →
      报修人确认关闭。费用 ≥5000 元登记后先入审批,通过后才能确认关闭;保内故障会提示走厂商保修。
    </NAlert>
    <NAlert v-if="errorMsg" type="error" style="margin-bottom: 12px">{{ errorMsg }}</NAlert>
    <NAlert v-if="resultMsg" type="success" style="margin-bottom: 12px">{{ resultMsg }}</NAlert>
    <div class="ios-card" style="margin-top: 16px">
      <div class="ios-card-body">

    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 0px">扫码报修</div>
    <NSpace style="margin-bottom: 12px">
      <NInput v-model:value="labelCode" placeholder="标签码(扫码)" style="width: 200px" />
      <NInput v-model:value="description" placeholder="故障描述" style="width: 220px" />
      <NInput v-model:value="photoUrl" placeholder="故障照片地址(先传到服务器目录再填地址)" style="width: 260px" />
      <NButton type="primary" @click="doScanRepair">一键报修</NButton>
    </NSpace>
    <NAlert v-if="scanResult" type="info" style="margin-bottom: 12px">
      {{ scanResult.asset_code }} {{ scanResult.name }} 存放地点:{{ scanResult.room_name ?? '未登记' }}
      保修状态:{{ scanResult.warranty_hint }}
    </NAlert>

    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20px">维修工单</div>
    <p>点“选中处理”可把单号填入下方派单/登记框,不用手填单号。</p>
    <NDataTable :bordered="false" :single-line="false"
      :columns="[
        { title: '单号', key: 'doc_no' },
        { title: '资产 id', key: 'asset_id' },
        { title: '报修人', key: 'reporter_name' },
        { title: '维修方', key: 'vendor' },
        { title: '费用(元)', key: 'cost' },
        { title: '状态', key: 'status' },
        {
          title: '处理', key: 'pick', width: 110,
          render: (r: RepairOrder) => h(
            NButton, { size: 'small', onClick: () => pickRepair(r) }, () => '选中处理',
          ),
        },
      ]"
      :data="repairs" :row-key="(r: RepairOrder) => r.id"
    />
    <NSpace style="margin-top: 8px">
      <NButton v-for="o in repairs.filter((i) => i.status === '待确认')" :key="`cf-${o.id}`" size="small" @click="doConfirm(o.id)">报修人确认关闭 {{ o.doc_no }}</NButton>
    </NSpace>

    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20px">派单 / 送修</div>
    <NSpace style="margin-bottom: 12px">
      <NInput v-model:value="dispatchId" placeholder="维修单 id" style="width: 120px" />
      <NInput v-model:value="assigneeName" placeholder="派单给(维修员)" style="width: 140px" />
      <NInput v-model:value="vendor" placeholder="维修方" style="width: 140px" />
      <NCheckbox v-model:checked="sendToRepair">同时送修</NCheckbox>
      <NButton @click="doDispatch">派单{{ sendToRepair ? '并送修' : '' }}</NButton>
    </NSpace>

    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20px">登记维修方、费用、结果</div>
    <p>费用 ≥5000 元登记后先入待审批,须走审批流通过后报修人才可确认关闭。</p>
    <NSpace style="margin-bottom: 12px">
      <NInput v-model:value="recordId" placeholder="维修单 id" style="width: 120px" />
      <NInput v-model:value="recordCost" placeholder="费用(元)" style="width: 120px" />
      <NInput v-model:value="recordResult" placeholder="维修结果" style="width: 220px" />
      <NButton @click="doRecord">登记维修结果</NButton>
    </NSpace>

    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20px">维修费用累计</div>
    <NSpace style="margin-bottom: 12px">
      <AssetPicker v-model="summaryAssetId" style="width: 320px" />
      <NButton @click="doSummary">查询累计维修费</NButton>
    </NSpace>
    <p v-if="summary">累计维修费 {{ summary.total_cost }} 元,已关闭 {{ summary.closed_count }} 单,未关闭 {{ summary.open_count }} 单,审批阈值 {{ summary.threshold }} 元。</p>
      </div>
    </div>
  </div>
</template>
