<script setup lang="ts">
import {
  NAlert, NButton, NDataTable, NInput, NSpace,
} from 'naive-ui'
import { onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import {
  confirmHandoverItem, confirmInTransfer, createTransfer, finalizeTransfer,
  generateHandover, listHandovers, listTransfers,
} from '@/api/asset'
import type { HandoverOrder, TransferOrder } from '@/api/asset'

// 学校资产管理系统一期第 3 批:调拨与移交(#37/#39/#40)。
// 未接路由(由收尾批统一接线);人员以 id 选择(演示页,实际使用时由组织数据带入)。

const resultMsg = ref('')
const errorMsg = ref('')

const assetId = ref('')
const toDept = ref('')
const toCustodianId = ref('')
const toRoomName = ref('')
const transferReason = ref('')
const fromUserId = ref('')
const toUserId = ref('')
const reasonType = ref('离职')
const labelCode = ref('')
const confirmOrderId = ref('')
const confirmItemId = ref('')

const transfers = ref<TransferOrder[]>([])
const handovers = ref<HandoverOrder[]>([])

async function load() {
  try {
    transfers.value = await listTransfers()
    handovers.value = await listHandovers()
  } catch (e) {
    errorMsg.value = (e as ApiError).detail ?? '加载失败'
  }
}

function showError(e: unknown) {
  errorMsg.value = (e as ApiError).detail ?? '操作失败'
  resultMsg.value = ''
}

async function doCreateTransfer() {
  try {
    const row = await createTransfer({
      asset_id: Number(assetId.value), to_dept: toDept.value,
      to_custodian_id: toCustodianId.value ? Number(toCustodianId.value) : undefined,
      to_room_name: toRoomName.value || undefined, reason: transferReason.value,
    })
    resultMsg.value = `调拨单 ${row.doc_no} 已创建,待调入部门确认`
    errorMsg.value = ''
    await load()
  } catch (e) { showError(e) }
}

async function doConfirmIn(id: number) {
  try {
    const row = await confirmInTransfer(id)
    resultMsg.value = `调拨单 ${row.doc_no} 调入部门已确认,进入审批`
    errorMsg.value = ''
    await load()
  } catch (e) { showError(e) }
}

async function doFinalize(id: number) {
  try {
    const row = await finalizeTransfer(id)
    resultMsg.value = `调拨单 ${row.doc_no} 已完成,责任与位置已变更`
    errorMsg.value = ''
    await load()
  } catch (e) { showError(e) }
}

async function doGenerateHandover() {
  try {
    const row = await generateHandover({
      from_user_id: Number(fromUserId.value), to_user_id: Number(toUserId.value),
      reason_type: reasonType.value,
    })
    resultMsg.value = `移交单 ${row.doc_no} 已生成,共 ${row.items.length} 件,待逐件扫码确认`
    errorMsg.value = ''
    await load()
  } catch (e) { showError(e) }
}

async function doConfirmItem() {
  try {
    const row = await confirmHandoverItem(
      Number(confirmOrderId.value), Number(confirmItemId.value), labelCode.value)
    resultMsg.value = `移交单 ${row.doc_no} 当前状态:${row.status}`
    errorMsg.value = ''
    await load()
  } catch (e) { showError(e) }
}

onMounted(load)
</script>

<template>
  <div class="ios-page">
    <h1 class="ios-title">调拨与移交</h1>
    <NAlert v-if="errorMsg" type="error" style="margin-bottom: 12px">{{ errorMsg }}</NAlert>
    <NAlert v-if="resultMsg" type="success" style="margin-bottom: 12px">{{ resultMsg }}</NAlert>
    <div class="ios-card" style="margin-top: 16px">
      <div class="ios-card-body">

    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 0px">部门间调拨</div>
    <NSpace style="margin-bottom: 12px">
      <NInput v-model:value="assetId" placeholder="资产 id" style="width: 120px" />
      <NInput v-model:value="toDept" placeholder="调入部门" style="width: 160px" />
      <NInput v-model:value="toCustodianId" placeholder="调入保管人 id" style="width: 140px" />
      <NInput v-model:value="toRoomName" placeholder="调入房间" style="width: 140px" />
      <NInput v-model:value="transferReason" placeholder="调拨事由" style="width: 180px" />
      <NButton type="primary" @click="doCreateTransfer">发起调拨</NButton>
    </NSpace>
    <NDataTable :bordered="false" :single-line="false"
      :columns="[
        { title: '单号', key: 'doc_no' },
        { title: '调出部门', key: 'from_dept' },
        { title: '调入部门', key: 'to_dept' },
        { title: '状态', key: 'status' },
      ]"
      :data="transfers" :row-key="(r: TransferOrder) => r.id"
    />
    <NSpace style="margin-top: 8px">
      <NButton v-for="o in transfers.filter((i) => i.status === '待调入确认')" :key="`in-${o.id}`" size="small" @click="doConfirmIn(o.id)">调入确认 {{ o.doc_no }}</NButton>
      <NButton v-for="o in transfers.filter((i) => i.status === '待完成')" :key="`fin-${o.id}`" size="small" @click="doFinalize(o.id)">完成调拨 {{ o.doc_no }}</NButton>
    </NSpace>

    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20pxpx">离职/调岗/退休移交</div>
    <NSpace style="margin-bottom: 12px">
      <NInput v-model:value="fromUserId" placeholder="移交人 id" style="width: 120px" />
      <NInput v-model:value="toUserId" placeholder="接收人 id" style="width: 120px" />
      <NInput v-model:value="reasonType" placeholder="原因:离职/调岗/退休" style="width: 160px" />
      <NButton type="primary" @click="doGenerateHandover">按人员生成移交单</NButton>
    </NSpace>
    <p>移交单按人员名下全部资产自动汇总生成(手动触发;未接人事系统,人事联动留接口)。</p>
    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20pxpx">逐件扫码确认</div>
    <NSpace style="margin-bottom: 12px">
      <NInput v-model:value="confirmOrderId" placeholder="移交单 id" style="width: 120px" />
      <NInput v-model:value="confirmItemId" placeholder="明细 id" style="width: 120px" />
      <NInput v-model:value="labelCode" placeholder="标签码(扫码)" style="width: 200px" />
      <NButton @click="doConfirmItem">扫码确认该件</NButton>
    </NSpace>
    <NDataTable :bordered="false" :single-line="false"
      :columns="[
        { title: '单号', key: 'doc_no' },
        { title: '移交人', key: 'from_user_name' },
        { title: '接收人', key: 'to_user_name' },
        { title: '原因', key: 'reason_type' },
        { title: '状态', key: 'status' },
      ]"
      :data="handovers" :row-key="(r: HandoverOrder) => r.id"
    />
      </div>
    </div>
  </div>
</template>
