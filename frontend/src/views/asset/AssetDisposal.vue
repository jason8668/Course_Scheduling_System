<script setup lang="ts">
import {
  NAlert, NButton, NDataTable, NInput, NPopconfirm, NSelect, NSpace,
} from 'naive-ui'
import { onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import {
  DISPOSAL_TYPES, appraiseDisposal, confirmDisposalRetire, createDisposal,
  createDisposalPackage, listDisposalMaterials, listDisposals, recordDisposalReply,
  selectDisposalOfficial, submitDisposalApproval,
} from '@/api/asset'
import type { DisposalOrder } from '@/api/asset'

// 学校资产管理系统一期第 5 批:处置与报废(M8 #54~#58)。
// 处置申请 + 鉴定 + 审批 + 申报材料包 + 核销回收;未接路由(由收尾批统一接线)。
// 处置单本身不改资产状态:资产须先转入待处置;核销须官方批复回填后手动确认。

const loading = ref(false)
const orders = ref<DisposalOrder[]>([])
const resultMsg = ref('')
const errorMsg = ref('')
const assetId = ref('')
const disposalType = ref<string>('scrap')
const reason = ref('')
const materialsRequired = ref<string[]>([])
const materialsChecked = ref<string[]>([])
const selectedId = ref('')
const appraisalConclusion = ref('建议处置')
const appraisalDetail = ref('')
const replyNo = ref('')

const typeOptions = DISPOSAL_TYPES.map((t) => ({ label: t.label, value: t.value }))
const conclusionOptions = [
  { label: '建议处置', value: '建议处置' },
  { label: '建议报废', value: '建议报废' },
  { label: '可继续使用', value: '可继续使用' },
]
const selected = () => orders.value.find((o) => o.id === Number(selectedId.value))

async function load() {
  loading.value = true
  errorMsg.value = ''
  try {
    orders.value = await listDisposals()
  } catch (e) {
    errorMsg.value = (e as ApiError).message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function loadMaterials() {
  try {
    const data = await listDisposalMaterials(disposalType.value)
    materialsRequired.value = data.materials_required
    materialsChecked.value = [...data.materials_required]
  } catch (e) {
    errorMsg.value = (e as ApiError).message || '材料清单加载失败'
  }
}

async function doCreate() {
  if (!assetId.value) {
    errorMsg.value = '请填写资产 ID(须先将资产转入待处置)'
    return
  }
  try {
    const order = await createDisposal({
      asset_id: Number(assetId.value), disposal_type: disposalType.value,
      reason: reason.value, materials: materialsChecked.value,
    })
    resultMsg.value = `处置申请已创建:${order.doc_no}`
    await load()
  } catch (e) {
    errorMsg.value = (e as ApiError).message || '创建失败'
  }
}

async function doAppraise() {
  if (!selectedId.value) return
  try {
    await appraiseDisposal(Number(selectedId.value), {
      conclusion: appraisalConclusion.value, detail: appraisalDetail.value,
    })
    resultMsg.value = appraisalConclusion.value === '可继续使用'
      ? '鉴定结论可继续使用,处置单已关闭,资产已回在库/在用'
      : '鉴定完成,处置单转待审批'
    await load()
  } catch (e) {
    errorMsg.value = (e as ApiError).message || '鉴定失败'
  }
}

async function doSubmitApproval() {
  if (!selectedId.value) return
  try {
    await submitDisposalApproval(Number(selectedId.value))
    resultMsg.value = '已提交分级处置审批(金额取资产原值)'
    await load()
  } catch (e) {
    errorMsg.value = (e as ApiError).message || '提交审批失败'
  }
}

async function doSelectOfficial() {
  if (!selectedId.value) return
  try {
    await selectDisposalOfficial(Number(selectedId.value))
    resultMsg.value = '已手动选择生成官方申报材料包'
    await load()
  } catch (e) {
    errorMsg.value = (e as ApiError).message || '选择失败'
  }
}

async function doPackage() {
  if (!selectedId.value) return
  try {
    const pkg = await createDisposalPackage(Number(selectedId.value))
    resultMsg.value = `申报材料包已生成:${pkg.package_no}`
    await load()
  } catch (e) {
    errorMsg.value = (e as ApiError).message || '生成材料包失败'
  }
}

async function doReply() {
  if (!selectedId.value || !replyNo.value) {
    errorMsg.value = '请填写官方批复文号'
    return
  }
  try {
    await recordDisposalReply(Number(selectedId.value), replyNo.value)
    resultMsg.value = '官方批复已回填,可以手动确认核销'
    await load()
  } catch (e) {
    errorMsg.value = (e as ApiError).message || '回填批复失败'
  }
}

async function doRetire() {
  if (!selectedId.value) return
  try {
    await confirmDisposalRetire(Number(selectedId.value))
    resultMsg.value = '已核销,编号封存,回收交接单已生成(待交接)'
    await load()
  } catch (e) {
    errorMsg.value = (e as ApiError).message || '核销失败'
  }
}

onMounted(async () => {
  await loadMaterials()
  await load()
})
</script>

<template>
  <div class="ios-page">
    <h1 class="ios-title">处置与报废</h1>
    <NAlert type="info" style="margin-bottom: 12px">
      处置申请只接受已转入待处置的资产,处置单本身不改状态;鉴定结论“可继续使用”时
      处置单关闭、资产回在库/在用;官方批复回填后才可手动确认核销。
    </NAlert>
    <NAlert v-if="errorMsg" type="error" style="margin-bottom: 12px">{{ errorMsg }}</NAlert>
    <NAlert v-if="resultMsg" type="success" style="margin-bottom: 12px">{{ resultMsg }}</NAlert>
    <div class="ios-card" style="margin-top: 16px">
      <div class="ios-card-body">

    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 0px">新建处置申请</div>
    <NSpace vertical>
      <NSpace>
        <NInput v-model:value="assetId" placeholder="资产 ID" style="width: 140px" />
        <NSelect
          v-model:value="disposalType" :options="typeOptions" style="width: 160px"
          @update:value="loadMaterials"
        />
        <NInput v-model:value="reason" placeholder="处置原因" style="width: 260px" />
        <NButton type="primary" @click="doCreate">创建处置申请</NButton>
      </NSpace>
      <p>应交材料:{{ materialsRequired.join('、') || '—' }}(缺材料不得提交)</p>
    </NSpace>

    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20pxpx">处置单</div>
    <NDataTable :bordered="false" :single-line="false"
      :columns="[
        { title: '处置单号', key: 'doc_no', width: 160 },
        { title: '资产 ID', key: 'asset_id', width: 90 },
        { title: '类型', key: 'disposal_type', width: 100 },
        { title: '状态', key: 'status', width: 110 },
        { title: '官方批复', key: 'official_reply_no', width: 160 },
      ]"
      :data="orders" :loading="loading" :row-key="(r: DisposalOrder) => r.id"
    />
    <NSpace style="margin-top: 8px">
      <NInput v-model:value="selectedId" placeholder="选中处置单 ID" style="width: 160px" />
      <NSelect v-model:value="appraisalConclusion" :options="conclusionOptions" style="width: 140px" />
      <NInput v-model:value="appraisalDetail" placeholder="鉴定说明" style="width: 200px" />
      <NButton @click="doAppraise">技术鉴定</NButton>
      <NButton @click="doSubmitApproval">提交审批</NButton>
    </NSpace>
    <NSpace style="margin-top: 8px">
      <NButton @click="doSelectOfficial">手动选择申报</NButton>
      <NButton @click="doPackage">生成申报材料包</NButton>
      <NInput v-model:value="replyNo" placeholder="官方批复文号" style="width: 200px" />
      <NButton @click="doReply">回填官方批复</NButton>
      <!-- 第 6 批 #84:核销不可逆(编号封存),二次确认;后端另有官方批复回填校验。 -->
      <NPopconfirm @positive-click="doRetire">
        <template #trigger><NButton type="warning">确认核销</NButton></template>
        确认核销吗?核销后资产编号封存不复用,不可恢复。
      </NPopconfirm>
    </NSpace>
    <p v-if="selected()">当前选中:{{ selected()?.doc_no }} 状态:{{ selected()?.status }}</p>
      </div>
    </div>
  </div>
</template>
