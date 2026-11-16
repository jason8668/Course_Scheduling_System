<script setup lang="ts">
import {
  NAlert, NButton, NDataTable, NInput, NSelect, NSpace,
} from 'naive-ui'
import { computed, h, onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import {
  confirmHandoverItem, confirmInTransfer, createTransfer, finalizeTransfer,
  generateHandover, listAssetUsers, listHandovers, listTransfers,
} from '@/api/asset'
import type { AssetUser, HandoverOrder, TransferOrder } from '@/api/asset'
import AssetPicker from '@/components/AssetPicker.vue'

// 学校资产管理系统一期第 3 批:调拨与移交(#37/#39/#40)。
// 资产按编号/名称搜索选择;人员按账号姓名选择(账号列表仅系统管理员可见,
// 非管理员仍可手填用户 id)。

const resultMsg = ref('')
const errorMsg = ref('')

const assetId = ref<number | null>(null)
const toDept = ref('')
const toCustodianId = ref<number | null>(null)
const toRoomName = ref('')
const transferReason = ref('')
const fromUserId = ref<number | null>(null)
const toUserId = ref<number | null>(null)
const toCustodianIdText = ref('')
const fromUserIdText = ref('')
const toUserIdText = ref('')
const reasonType = ref('离职')
const labelCode = ref('')
const confirmOrderId = ref('')
const confirmItemId = ref('')

const transfers = ref<TransferOrder[]>([])
const handovers = ref<HandoverOrder[]>([])
const users = ref<AssetUser[]>([])
const usersFailed = ref(false)
const userOptions = computed(() => users.value.map((u) => ({
  label: `${u.display_name}（${u.username}·${u.roles.join('/')}）`,
  value: u.id,
})))

async function load() {
  try {
    transfers.value = await listTransfers()
    handovers.value = await listHandovers()
  } catch (e) {
    errorMsg.value = (e as ApiError).detail ?? '加载失败'
  }
}

async function loadUsers() {
  try {
    const data = await listAssetUsers()
    users.value = Array.isArray(data) ? data : []
  } catch {
    // 账号列表仅系统管理员可见:非管理员走手填 id 兜底,不阻塞本页。
    usersFailed.value = true
  }
}

function showError(e: unknown) {
  errorMsg.value = (e as ApiError).detail ?? '操作失败'
  resultMsg.value = ''
}

async function doCreateTransfer() {
  if (!assetId.value) {
    errorMsg.value = '请先在上方搜索并选择资产'
    resultMsg.value = ''
    return
  }
  try {
    const row = await createTransfer({
      asset_id: assetId.value, to_dept: toDept.value,
      to_custodian_id: usersFailed.value
        ? (toCustodianIdText.value ? Number(toCustodianIdText.value) : undefined)
        : (toCustodianId.value ?? undefined),
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
  const fromId = usersFailed.value ? Number(fromUserIdText.value) : fromUserId.value
  const toId = usersFailed.value ? Number(toUserIdText.value) : toUserId.value
  if (!fromId || !toId) {
    errorMsg.value = '请先选择移交人和接收人'
    resultMsg.value = ''
    return
  }
  try {
    const row = await generateHandover({
      from_user_id: fromId, to_user_id: toId,
      reason_type: reasonType.value,
    })
    resultMsg.value = `移交单 ${row.doc_no} 已生成,共 ${row.items.length} 件,待逐件扫码确认`
    errorMsg.value = ''
    await load()
  } catch (e) { showError(e) }
}

function pickHandover(row: HandoverOrder) {
  confirmOrderId.value = String(row.id)
  resultMsg.value = `已选中移交单 ${row.doc_no},请填明细 id 并扫标签码确认`
  errorMsg.value = ''
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

onMounted(() => { load(); loadUsers() })
</script>

<template>
  <div class="ios-page">
    <h1 class="ios-title">调拨与移交</h1>
    <NAlert type="info" style="margin-bottom: 12px">
      调拨三步:发起调拨 → 调入部门点“调入确认” → 点“完成调拨”,责任与位置随之变更。
      移交两步:按人员生成移交单(名下全部资产自动汇总) → 逐件扫标签码确认。
    </NAlert>
    <NAlert v-if="errorMsg" type="error" style="margin-bottom: 12px">{{ errorMsg }}</NAlert>
    <NAlert v-if="resultMsg" type="success" style="margin-bottom: 12px">{{ resultMsg }}</NAlert>
    <div class="ios-card" style="margin-top: 16px">
      <div class="ios-card-body">

    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 0px">部门间调拨</div>
    <NSpace style="margin-bottom: 12px">
      <AssetPicker v-model="assetId" style="width: 320px" />
      <NInput v-model:value="toDept" placeholder="调入部门" style="width: 160px" />
      <NSelect
        v-if="!usersFailed" v-model:value="toCustodianId" :options="userOptions"
        filterable clearable placeholder="调入保管人(按姓名选)" style="width: 200px"
      />
      <NInput v-else v-model:value="toCustodianIdText" placeholder="调入保管人 id" style="width: 140px" />
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

    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20px">离职/调岗/退休移交</div>
    <NSpace style="margin-bottom: 12px">
      <template v-if="!usersFailed">
        <NSelect
          v-model:value="fromUserId" :options="userOptions" filterable clearable
          placeholder="移交人(按姓名选)" style="width: 200px"
        />
        <NSelect
          v-model:value="toUserId" :options="userOptions" filterable clearable
          placeholder="接收人(按姓名选)" style="width: 200px"
        />
      </template>
      <template v-else>
        <NInput v-model:value="fromUserIdText" placeholder="移交人 id" style="width: 120px" />
        <NInput v-model:value="toUserIdText" placeholder="接收人 id" style="width: 120px" />
      </template>
      <NInput v-model:value="reasonType" placeholder="原因:离职/调岗/退休" style="width: 160px" />
      <NButton type="primary" @click="doGenerateHandover">按人员生成移交单</NButton>
    </NSpace>
    <p>移交单按移交人名下全部资产自动汇总生成;人员变动请先在人事处确认,再手动生成本单。账号列表只对系统管理员开放,其他管理员请直接填用户 id。</p>
    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20px">逐件扫码确认</div>
    <p>先点下方移交单的“选中确认”,再扫标签码;明细 id 是移交单里每件资产的行号,点“选中确认”后按提示填。</p>
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
        {
          title: '确认', key: 'pick', width: 110,
          render: (r: HandoverOrder) => h(
            NButton,
            { size: 'small', onClick: () => pickHandover(r) },
            () => '选中确认',
          ),
        },
      ]"
      :data="handovers" :row-key="(r: HandoverOrder) => r.id"
    />
      </div>
    </div>
  </div>
</template>
