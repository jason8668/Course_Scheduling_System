<script setup lang="ts">
import {
  NAlert, NButton, NDataTable, NInput, NSelect, NSpace,
} from 'naive-ui'
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import {
  deleteAssetAttachment, getAssetCard, getAssetTimeline, listAssetAttachments, reprintAssetLabel,
  selectForSync, uploadAssetAttachment, uploadAssetAttachmentFiles,
} from '@/api/asset'
import type { AssetAttachment, AssetCard, TimelineEntry } from '@/api/asset'
import AssetPicker from '@/components/AssetPicker.vue'

// 学校资产管理系统一期第 2 批:资产卡(#10/#12/#28/#87)。
// 四区 + 扩展区 + 附件归档 + 勾选同步按钮;第 3 批接入真实履历时间轴(#6)。
// 打开方式:台账行点编号带 ?id= 进来,或在本页上方按编号/名称搜索后打开。
// 之前只靠父级传 assetId、路由又不传参,导致本页打开是空白,已修。

const props = defineProps<{ assetId?: number }>()

const route = useRoute()
const router = useRouter()
const queryId = route.query.id ? Number(route.query.id) : null
const currentId = ref<number | null>(
  props.assetId ?? (queryId && Number.isFinite(queryId) ? queryId : null),
)
const pickedId = ref<number | null>(null)

const loading = ref(false)
const notFound = ref(false)
const card = ref<AssetCard | null>(null)
const attachments = ref<AssetAttachment[]>([])
const timeline = ref<TimelineEntry[]>([])
const resultMsg = ref('')
const uploadError = ref('')
const uploading = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const fileType = ref('发票')
const fileName = ref('')
const filePath = ref('')

const fileTypeOptions = [
  { label: '发票', value: '发票' },
  { label: '合同', value: '合同' },
  { label: '验收照片', value: '验收照片' },
  { label: '设备照片', value: '设备照片' },
  { label: '其他', value: '其他' },
]

async function load() {
  if (!currentId.value) {
    card.value = null
    attachments.value = []
    timeline.value = []
    return
  }
  loading.value = true
  notFound.value = false
  try {
    card.value = await getAssetCard(currentId.value)
    attachments.value = await listAssetAttachments(currentId.value)
    timeline.value = await getAssetTimeline(currentId.value)
  } catch (e) {
    if ((e as ApiError).status === 404) notFound.value = true
  } finally {
    loading.value = false
  }
}

function openPicked() {
  if (!pickedId.value) return
  currentId.value = pickedId.value
  resultMsg.value = ''
  load()
}

function goLedger() {
  router.push({ name: 'asset-ledger' })
}

async function doUpload() {
  if (!fileName.value || !filePath.value || !card.value) return
  await uploadAssetAttachment(card.value.id, {
    file_type: fileType.value, file_name: fileName.value, file_path: filePath.value,
  })
  resultMsg.value = `附件 ${fileName.value} 已归档`
  fileName.value = ''
  filePath.value = ''
  await load()
}

/** 附件直传(#12):选多个文件直接传服务器,失败显示后端返回的原因。 */
async function onFilesPicked() {
  const input = fileInput.value
  if (!input?.files?.length || !card.value) return
  const files = Array.from(input.files)
  input.value = ''
  uploadError.value = ''
  uploading.value = true
  try {
    const rows = await uploadAssetAttachmentFiles(card.value.id, files, fileType.value)
    resultMsg.value = `已上传 ${rows.length} 个附件`
    await load()
  } catch (e) {
    uploadError.value = (e as ApiError).detail || (e as Error).message || '上传失败'
  } finally {
    uploading.value = false
  }
}

async function doDelete(id: number) {
  await deleteAssetAttachment(id)
  resultMsg.value = '附件已删除(留痕)'
  await load()
}

async function doSelectSync() {
  if (!card.value) return
  const res = await selectForSync([card.value.id])
  resultMsg.value = res.succeeded.length
    ? '已勾选同步,进入待同步池'
    : `勾选失败:${res.failed.map((f) => f.reason).join('；')}`
  await load()
}

async function doReprint() {
  if (!card.value) return
  await reprintAssetLabel(card.value.id)
  resultMsg.value = '标签已补打(已记审计)'
}

onMounted(load)
</script>

<template>
  <div class="ios-page">
    <h1 class="ios-title">资产卡</h1>
    <NAlert type="info" style="margin-bottom: 12px">
      先在下方输入资产编号或名称、选中资产后点“打开资产卡”;也可以从“资产台账”点任意一行的编号直接进来。
      卡片分基本信息、财务、使用、特性四个区,最下方是校内扩展区(不同步到上级系统)。
    </NAlert>
    <NSpace style="margin-bottom: 12px">
      <AssetPicker v-model="pickedId" style="width: 320px" />
      <NButton type="primary" :disabled="!pickedId" @click="openPicked">打开资产卡</NButton>
      <NButton @click="goLedger">返回资产台账</NButton>
    </NSpace>
    <NAlert v-if="notFound" type="error">资产卡不存在,请核对编号后重新搜索</NAlert>
    <p v-else-if="!card && !loading">还没有打开任何资产卡,请先在上方搜索并打开。</p>
    <div v-else-if="card" :key="card.id">
    <div class="ios-card" style="margin-top: 16px">
      <div class="ios-card-body">
      <NSpace style="margin-bottom: 12px">
        <NButton type="primary" :disabled="card.sync_status !== '未同步'" @click="doSelectSync">勾选同步</NButton>
        <NButton @click="doReprint">补打标签</NButton>
        <span>同步状态:{{ card.sync_status }};入账:{{ card.is_booked ? '已入账' : '未入账' }}</span>
      </NSpace>
      <NAlert v-if="resultMsg" type="success" style="margin-bottom: 12px">{{ resultMsg }}</NAlert>
      <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 0px">基本信息区</div>
      <p>资产编号:{{ card.asset_code }};官方编号:{{ card.official_code ?? '未回填' }};标签码:{{ card.label_code }}</p>
      <p>名称:{{ card.name }};分类:{{ card.category_code }};规格型号:{{ card.spec_model ?? '—' }};单位:{{ card.unit }}</p>
      <p>取得方式:{{ card.acquire_method ?? '—' }};来源:{{ card.source ?? '—' }};供应商:{{ card.supplier ?? '—' }};入库批次:{{ card.batch_no ?? '—' }}</p>
      <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20px">财务信息区</div>
      <p>原值:{{ card.original_value ?? '—' }} 元;资金来源:{{ card.funding_source ?? '—' }};入账凭证号:{{ card.voucher_no ?? '未回填' }}</p>
      <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20px">使用信息区</div>
      <p>状态:{{ card.status }};管理部门:{{ card.manage_dept ?? '—' }};使用部门:{{ card.use_dept ?? '—' }};保管人:{{ card.custodian_name ?? '—' }}</p>
      <p>校区:{{ card.campus ?? '—' }};楼栋:{{ card.building ?? '—' }};房间:{{ card.room_name ?? '—' }};领用状态:{{ card.borrow_status }}</p>
      <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20px">特性信息区</div>
      <p>{{ card.attributes ? JSON.stringify(card.attributes) : '无特性字段' }}</p>
      <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20px">校内扩展区(不同步)</div>
      <p>{{ card.ext ? JSON.stringify(card.ext) : '无扩展字段' }}</p>
      <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20px">附件与影像归档</div>
      <p>点“上传附件”可直接传文件(单个 ≤20MB,支持图片/PDF/Word/Excel);也可以把已在服务器目录的文件按路径归档。</p>
      <NAlert v-if="uploadError" type="error" style="margin-bottom: 12px">{{ uploadError }}</NAlert>
      <NSpace style="margin-bottom: 12px">
        <NSelect v-model:value="fileType" :options="fileTypeOptions" style="width: 120px" />
        <input
          ref="fileInput" type="file" multiple style="display: none"
          accept=".jpg,.jpeg,.png,.webp,.pdf,.doc,.docx,.xls,.xlsx"
          @change="onFilesPicked"
        >
        <NButton type="primary" :loading="uploading" @click="fileInput?.click()">上传附件</NButton>
        <NInput v-model:value="fileName" placeholder="文件名(如 示例发票.pdf)" style="width: 200px" />
        <NInput v-model:value="filePath" placeholder="存储路径/对象键" style="width: 260px" />
        <NButton @click="doUpload">归档附件</NButton>
      </NSpace>
      <NDataTable :bordered="false" :single-line="false"
        :columns="[
          { title: '类型', key: 'file_type', width: 100 },
          { title: '文件名', key: 'file_name' },
          { title: '存储路径', key: 'file_path' },
        ]"
        :data="attachments" :row-key="(r: AssetAttachment) => r.id"
      />
      <NSpace style="margin-top: 8px">
        <NButton
          v-for="a in attachments" :key="a.id" size="small"
          @click="doDelete(a.id)"
        >删除 {{ a.file_name }}</NButton>
      </NSpace>
      <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20px">履历时间轴</div>
      <p v-if="timeline.length === 0">暂无履历记录</p>
      <NDataTable :bordered="false" :single-line="false"
        v-else
        :columns="[
          { title: '时间', key: 'time', width: 180 },
          { title: '类型', key: 'type', width: 90 },
          { title: '事件', key: 'title' },
          { title: '详情', key: 'detail' },
        ]"
        :data="timeline" :row-key="(r: TimelineEntry) => `${r.time}-${r.type}-${r.title}`"
      />
      </div>
    </div>
    </div>
    <p v-else-if="loading">加载中…</p>
  </div>
</template>
