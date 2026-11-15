<script setup lang="ts">
import {
  NAlert, NButton, NDataTable, NInput, NSelect, NSpace,
} from 'naive-ui'
import { onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import {
  checkoutReservation, confirmIssueScan, createBorrow, createIssue,
  createReservation, createReturn, issueAsset, listBorrows, listIssues,
  listReservations, listReturns, scanReturn,
} from '@/api/asset'
import type {
  BorrowOrder, IssueOrder, Reservation, ReturnOrder,
} from '@/api/asset'

// 学校资产管理系统一期第 3 批:领用/借用/归还/预约统一入口(#30~#34)。
// 未接路由(由收尾批统一接线);资产以 id 选择(演示页,实际使用时由扫码/台账带入)。

const tab = ref('issue')
const tabOptions = [
  { label: '领用', value: 'issue' },
  { label: '借用', value: 'borrow' },
  { label: '预约', value: 'reservation' },
  { label: '归还', value: 'return' },
]
const resultMsg = ref('')
const errorMsg = ref('')

const assetId = ref('')
const reason = ref('')
const useDept = ref('')
const dueAt = ref('')
const startAt = ref('')
const endAt = ref('')
const purpose = ref('')
const labelCode = ref('')
const scanOrderId = ref('')
const returnResult = ref<'完好' | '损坏'>('完好')
const damageNote = ref('')

const issues = ref<IssueOrder[]>([])
const borrows = ref<BorrowOrder[]>([])
const reservations = ref<Reservation[]>([])
const returns = ref<ReturnOrder[]>([])

async function load() {
  try {
    issues.value = await listIssues()
    borrows.value = await listBorrows()
    reservations.value = await listReservations()
    returns.value = await listReturns()
  } catch (e) {
    errorMsg.value = (e as ApiError).detail ?? '加载失败'
  }
}

function showError(e: unknown) {
  errorMsg.value = (e as ApiError).detail ?? '操作失败'
  resultMsg.value = ''
}

async function doCreateIssue() {
  try {
    const row = await createIssue({
      asset_id: Number(assetId.value), use_dept: useDept.value || undefined, reason: reason.value,
    })
    resultMsg.value = `领用申请已提交,单号 ${row.doc_no},待审批`
    errorMsg.value = ''
    await load()
  } catch (e) { showError(e) }
}

async function doIssue(id: number) {
  try {
    const row = await issueAsset(id)
    resultMsg.value = `领用单 ${row.doc_no} 已发放,资产转为在用`
    errorMsg.value = ''
    await load()
  } catch (e) { showError(e) }
}

async function doConfirmScan() {
  try {
    const row = await confirmIssueScan(Number(scanOrderId.value), labelCode.value)
    resultMsg.value = `领用单 ${row.doc_no} 扫码确认完成`
    errorMsg.value = ''
    await load()
  } catch (e) { showError(e) }
}

async function doCreateBorrow() {
  try {
    const row = await createBorrow({
      asset_id: Number(assetId.value), reason: reason.value, due_at: dueAt.value,
    })
    resultMsg.value = `借用单 ${row.doc_no} 已创建,资产转为借出`
    errorMsg.value = ''
    await load()
  } catch (e) { showError(e) }
}

async function doCreateReservation() {
  try {
    const row = await createReservation({
      asset_id: Number(assetId.value),
      start_at: startAt.value, end_at: endAt.value, purpose: purpose.value,
    })
    resultMsg.value = `预约单 ${row.doc_no} 已创建`
    errorMsg.value = ''
    await load()
  } catch (e) { showError(e) }
}

async function doCheckout(id: number) {
  try {
    const row = await checkoutReservation(id)
    resultMsg.value = `预约单 ${row.doc_no} 已领用,转为借用单`
    errorMsg.value = ''
    await load()
  } catch (e) { showError(e) }
}

async function doCreateReturn() {
  try {
    const row = await createReturn({ asset_id: Number(assetId.value) })
    resultMsg.value = `归还单 ${row.doc_no} 已创建,请扫码验收`
    errorMsg.value = ''
    await load()
  } catch (e) { showError(e) }
}

async function doScanReturn() {
  try {
    const row = await scanReturn(Number(scanOrderId.value), {
      label_code: labelCode.value, result: returnResult.value, damage_note: damageNote.value,
    })
    resultMsg.value = returnResult.value === '完好'
      ? `归还单 ${row.doc_no} 验收完好,资产已回在库`
      : `归还单 ${row.doc_no} 验收损坏,已转维修(维修占位单待 B4 接入)`
    errorMsg.value = ''
    await load()
  } catch (e) { showError(e) }
}

onMounted(load)
</script>

<template>
  <div class="ios-page">
    <h1 class="ios-title">领用借用归还</h1>
    <NAlert v-if="errorMsg" type="error" style="margin-bottom: 12px">{{ errorMsg }}</NAlert>
    <NAlert v-if="resultMsg" type="success" style="margin-bottom: 12px">{{ resultMsg }}</NAlert>
    <NSpace style="margin-bottom: 12px">
      <NSelect v-model:value="tab" :options="tabOptions" style="width: 140px" />
      <NInput v-model:value="assetId" placeholder="资产 id" style="width: 120px" />
    </NSpace>
    <div class="ios-card" style="margin-top: 16px">
      <div class="ios-card-body">

    <div v-if="tab === 'issue'">
      <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 0px">长期领用申请</div>
      <NSpace style="margin-bottom: 12px">
        <NInput v-model:value="useDept" placeholder="使用部门" style="width: 160px" />
        <NInput v-model:value="reason" placeholder="领用事由" style="width: 220px" />
        <NButton type="primary" @click="doCreateIssue">提交领用申请</NButton>
      </NSpace>
      <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20pxpx">领用确认(扫码)</div>
      <NSpace style="margin-bottom: 12px">
        <NInput v-model:value="scanOrderId" placeholder="领用单 id" style="width: 120px" />
        <NInput v-model:value="labelCode" placeholder="标签码(扫码)" style="width: 200px" />
        <NButton @click="doConfirmScan">扫码确认接收</NButton>
      </NSpace>
      <NDataTable :bordered="false" :single-line="false"
        :columns="[
          { title: '单号', key: 'doc_no' },
          { title: '申请人', key: 'applicant_name' },
          { title: '状态', key: 'status' },
          { title: '操作', key: 'actions', render: (r: IssueOrder) => r.status === '待发放' ? '可发放' : '' },
        ]"
        :data="issues" :row-key="(r: IssueOrder) => r.id"
      />
      <NSpace style="margin-top: 8px">
        <NButton v-for="o in issues.filter((i) => i.status === '待发放')" :key="o.id" size="small" @click="doIssue(o.id)">发放 {{ o.doc_no }}</NButton>
      </NSpace>
    </div>

    <div v-if="tab === 'borrow'">
      <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 0px">短期借用</div>
      <NSpace style="margin-bottom: 12px">
        <NInput v-model:value="reason" placeholder="借用事由" style="width: 220px" />
        <NInput v-model:value="dueAt" placeholder="归还时间(如 2026-11-20T17:00:00)" style="width: 260px" />
        <NButton type="primary" @click="doCreateBorrow">提交借用</NButton>
      </NSpace>
      <NDataTable :bordered="false" :single-line="false"
        :columns="[
          { title: '单号', key: 'doc_no' },
          { title: '借用人', key: 'borrower_name' },
          { title: '归还时间', key: 'due_at' },
          { title: '状态', key: 'status' },
        ]"
        :data="borrows" :row-key="(r: BorrowOrder) => r.id"
      />
    </div>

    <div v-if="tab === 'reservation'">
      <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 0px">公用资产预约</div>
      <NSpace style="margin-bottom: 12px">
        <NInput v-model:value="startAt" placeholder="开始时间" style="width: 220px" />
        <NInput v-model:value="endAt" placeholder="结束时间" style="width: 220px" />
        <NInput v-model:value="purpose" placeholder="用途" style="width: 180px" />
        <NButton type="primary" @click="doCreateReservation">提交预约</NButton>
      </NSpace>
      <NDataTable :bordered="false" :single-line="false"
        :columns="[
          { title: '单号', key: 'doc_no' },
          { title: '预约人', key: 'reserver_name' },
          { title: '开始', key: 'start_at' },
          { title: '结束', key: 'end_at' },
          { title: '状态', key: 'status' },
        ]"
        :data="reservations" :row-key="(r: Reservation) => r.id"
      />
      <NSpace style="margin-top: 8px">
        <NButton v-for="o in reservations.filter((i) => i.status === '待领用')" :key="o.id" size="small" @click="doCheckout(o.id)">领用 {{ o.doc_no }}</NButton>
      </NSpace>
    </div>

    <div v-if="tab === 'return'">
      <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 0px">归还验收</div>
      <NSpace style="margin-bottom: 12px">
        <NButton type="primary" @click="doCreateReturn">新建归还单</NButton>
      </NSpace>
      <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20pxpx">扫码归还</div>
      <NSpace style="margin-bottom: 12px">
        <NInput v-model:value="scanOrderId" placeholder="归还单 id" style="width: 120px" />
        <NInput v-model:value="labelCode" placeholder="标签码(扫码)" style="width: 200px" />
        <NSelect v-model:value="returnResult" :options="[{ label: '完好', value: '完好' }, { label: '损坏', value: '损坏' }]" style="width: 100px" />
        <NInput v-model:value="damageNote" placeholder="损坏说明" style="width: 200px" />
        <NButton @click="doScanReturn">扫码验收</NButton>
      </NSpace>
      <NDataTable :bordered="false" :single-line="false"
        :columns="[
          { title: '单号', key: 'doc_no' },
          { title: '归还人', key: 'returner_name' },
          { title: '结果', key: 'result' },
          { title: '状态', key: 'status' },
        ]"
        :data="returns" :row-key="(r: ReturnOrder) => r.id"
      />
    </div>
      </div>
    </div>
  </div>
</template>
