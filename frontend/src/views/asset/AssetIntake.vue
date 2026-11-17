<script setup lang="ts">
import {
  NAlert, NButton, NDataTable, NInput, NSelect, NSpace,
} from 'naive-ui'
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import { apiGet } from '@/api/client'
import {
  bookingPendingExportUrl, bulkCreateFromAcceptance, confirmAcceptance,
  confirmBooking, createAcceptance, createCardsFromAcceptance, INTAKE_TYPES,
  listAcceptances, listBookingPending,
} from '@/api/asset'
import type { Acceptance, AssetCard } from '@/api/asset'

// 学校资产管理系统一期第 2 批:入库验收(#19~#28)。
// 六类入口同一验收流程:建验收单 → 验收确认 → 建卡/批量建卡;
// 验收不通过不得建卡;待入账清单由财务回填凭证号。

const router = useRouter()

const loading = ref(false)
const forbidden = ref(false)
const acceptances = ref<Acceptance[]>([])
const pending = ref<AssetCard[]>([])
const pendingTotal = ref(0)
const pendingValue = ref(0)
const resultMsg = ref('')

const intakeType = ref('self_purchase')
const sourceContract = ref('')
const sourceExtra = ref('')
const acceptorName = ref('')
const cardName = ref('')
const cardCategory = ref('A0203')
const cardValue = ref('')
const bulkQty = ref('3')
const voucherNo = ref('')
// 建卡管理部门改下拉(#76):口径走部门字典,不再手填自由文本。
const cardDept = ref('')
const deptOptions = ref([{ label: '管理部门(不填)', value: '' }])

const intakeOptions = INTAKE_TYPES.map((t) => ({ label: t.label, value: t.value }))

async function load() {
  loading.value = true
  forbidden.value = false
  try {
    acceptances.value = await listAcceptances()
    const data = await listBookingPending()
    pending.value = data.items
    pendingTotal.value = data.total
    pendingValue.value = data.total_value
    const depts = await apiGet<Array<{ name: string }>>('/asset/departments?is_active=true')
    deptOptions.value = [
      { label: '管理部门(不填)', value: '' },
      ...depts.map((d) => ({ label: d.name, value: d.name })),
    ]
  } catch (e) {
    if ((e as ApiError).status === 403) forbidden.value = true
  } finally {
    loading.value = false
  }
}

function sourceDoc() {
  const doc: Record<string, unknown> = {}
  if (sourceContract.value) doc.contract_no = sourceContract.value
  if (sourceExtra.value) doc.note = sourceExtra.value
  return doc
}

async function doCreateAcceptance() {
  const row = await createAcceptance({
    intake_type: intakeType.value,
    source_doc: sourceDoc(),
    acceptors: acceptorName.value ? [acceptorName.value] : [],
  })
  resultMsg.value = `验收单 ${row.acceptance_no} 已创建,待验收`
  await load()
}

async function doConfirm(id: number, result: '通过' | '不通过') {
  const row = await confirmAcceptance(id, { result })
  resultMsg.value = `验收单 ${row.acceptance_no} 已${result}`
  await load()
}

function goLedger() {
  router.push({ name: 'asset-ledger' })
}

async function doCreateCards(id: number) {
  if (!cardName.value) return
  const res = await createCardsFromAcceptance(id, {
    items: [{
      name: cardName.value, category_code: cardCategory.value,
      original_value: cardValue.value ? Number(cardValue.value) : undefined,
      manage_dept: cardDept.value || undefined,
    }],
  })
  resultMsg.value = `建卡:成功 ${res.succeeded.length} 件,失败 ${res.failed.length} 件`
    + (res.failed.length ? `(${res.failed.map((f) => f.reason).join('；')})` : '')
  await load()
}

async function doBulkCreate(id: number) {
  if (!cardName.value) return
  const res = await bulkCreateFromAcceptance(id, {
    template: {
      name: cardName.value, category_code: cardCategory.value,
      original_value: cardValue.value ? Number(cardValue.value) : undefined,
      manage_dept: cardDept.value || undefined,
    },
    quantity: Number(bulkQty.value) || 1,
  })
  resultMsg.value = `批量建卡:成功 ${res.succeeded.length} 件,失败 ${res.failed.length} 件`
  await load()
}

function doExportPending() {
  window.open(bookingPendingExportUrl(), '_blank')
}

async function doBook(id: number) {
  if (!voucherNo.value) return
  await confirmBooking(id, voucherNo.value)
  resultMsg.value = '入账凭证号已回填,资产转正式状态'
  voucherNo.value = ''
  await load()
}

onMounted(load)
</script>

<template>
  <div class="ios-page">
    <h1 class="ios-title">入库验收</h1>
    <NAlert type="info" style="margin-bottom: 12px">
      入库分四步:第 1 步新建验收单 → 第 2 步点“验收通过”(不通过的不得建卡) →
      第 3 步先在下方填好建卡名称、分类、原值,再点对应验收单的“建卡/批量建卡” →
      第 4 步财务在“待入账清单”回填凭证号后转正式状态。建卡后同步状态默认为未同步,需在台账手动勾选才上报。
    </NAlert>
    <NAlert v-if="forbidden" type="error" style="margin-bottom: 12px">权限不足</NAlert>
    <NAlert v-if="resultMsg" type="success" style="margin-bottom: 12px">
      {{ resultMsg }}
      <NButton v-if="resultMsg.includes('建卡')" size="small" style="margin-left: 8px" @click="goLedger">去资产台账查看</NButton>
    </NAlert>
    <div class="ios-card" style="margin-top: 16px">
      <div class="ios-card-body">

    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 0px">新建验收单</div>
    <NSpace style="margin-bottom: 12px">
      <NSelect v-model:value="intakeType" :options="intakeOptions" style="width: 220px" />
      <NInput v-model:value="sourceContract" placeholder="来源凭证:合同号/调拨单号等" style="width: 240px" />
      <NInput v-model:value="sourceExtra" placeholder="来源凭证备注:捐赠方/价值依据等" style="width: 240px" />
      <NInput v-model:value="acceptorName" placeholder="验收人姓名" style="width: 120px" />
      <NButton type="primary" @click="doCreateAcceptance">新建验收单</NButton>
    </NSpace>

    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20px">验收单列表</div>
    <p>建卡前先填好下面四项(名称必填,分类默认 A0203 通用设备,原值填采购价,批量建卡填件数),再点对应验收单的建卡按钮。</p>
    <NSpace vertical style="margin-bottom: 12px">
      <NSpace>
        <NInput v-model:value="cardName" placeholder="建卡名称(必填)" style="width: 180px" />
        <NInput v-model:value="cardCategory" placeholder="分类代码(如 A0203)" style="width: 140px" />
        <NInput v-model:value="cardValue" placeholder="原值(元)" style="width: 120px" />
        <NSelect v-model:value="cardDept" :options="deptOptions" placeholder="管理部门" style="width: 140px" />
        <NInput v-model:value="bulkQty" placeholder="批量件数" style="width: 100px" />
      </NSpace>
    </NSpace>
    <NDataTable :bordered="false" :single-line="false"
      :columns="[
        { title: '验收单号', key: 'acceptance_no', width: 160 },
        { title: '入库类型', key: 'intake_type', width: 150 },
        { title: '状态', key: 'status', width: 100 },
        { title: '批次号', key: 'batch_no', width: 140 },
      ]"
      :data="acceptances" :loading="loading" :row-key="(r: Acceptance) => r.id"
    />
    <NSpace style="margin: 8px 0 24px">
      <template v-for="a in acceptances" :key="a.id">
        <NButton v-if="a.status === '待验收'" size="small" @click="doConfirm(a.id, '通过')">验收通过 {{ a.acceptance_no }}</NButton>
        <NButton v-if="a.status === '待验收'" size="small" @click="doConfirm(a.id, '不通过')">验收不通过 {{ a.acceptance_no }}</NButton>
        <NButton v-if="a.status === '验收通过' || a.status === '已建卡'" size="small" :disabled="!cardName" @click="doCreateCards(a.id)">建卡 {{ a.acceptance_no }}</NButton>
        <NButton v-if="a.status === '验收通过' || a.status === '已建卡'" size="small" :disabled="!cardName" @click="doBulkCreate(a.id)">批量建卡 {{ a.acceptance_no }}</NButton>
      </template>
    </NSpace>

    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20px">待入账清单(共 {{ pendingTotal }} 件,总价值 {{ pendingValue }} 元)</div>
    <p>建卡后资产先是“未入账”状态:财务填入账凭证号、点对应行的“回填凭证”,资产才转正式状态。</p>
    <NSpace style="margin-bottom: 12px">
      <NInput v-model:value="voucherNo" placeholder="入账凭证号" style="width: 200px" />
      <NButton @click="doExportPending">导出未回填清单</NButton>
    </NSpace>
    <NDataTable :bordered="false" :single-line="false"
      :columns="[
        { title: '资产编号', key: 'asset_code', width: 150 },
        { title: '名称', key: 'name' },
        { title: '原值(元)', key: 'original_value', width: 100 },
        { title: '凭证号', key: 'voucher_no', width: 140 },
      ]"
      :data="pending" :row-key="(r: AssetCard) => r.id"
    />
    <NSpace style="margin-top: 8px">
      <NButton
        v-for="p in pending" :key="p.id" size="small"
        :disabled="!voucherNo" @click="doBook(p.id)"
      >回填凭证 {{ p.asset_code }}</NButton>
    </NSpace>
      </div>
    </div>
  </div>
</template>
