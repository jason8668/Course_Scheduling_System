<script setup lang="ts">
import {
  NAlert, NButton, NDataTable, NInput, NSelect, NSpace,
} from 'naive-ui'
import { onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import {
  deleteAssetAttachment, getAssetCard, getAssetTimeline, listAssetAttachments, reprintAssetLabel,
  selectForSync, uploadAssetAttachment,
} from '@/api/asset'
import type { AssetAttachment, AssetCard, TimelineEntry } from '@/api/asset'

// 学校资产管理系统一期第 2 批:资产卡(#10/#12/#28/#87)。
// 四区 + 扩展区 + 附件归档 + 勾选同步按钮;第 3 批接入真实履历时间轴(#6)。
// 未接路由(由收尾批统一接线);assetId 由父级传入。

const props = defineProps<{ assetId: number }>()

const loading = ref(false)
const notFound = ref(false)
const card = ref<AssetCard | null>(null)
const attachments = ref<AssetAttachment[]>([])
const timeline = ref<TimelineEntry[]>([])
const resultMsg = ref('')
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
  loading.value = true
  notFound.value = false
  try {
    card.value = await getAssetCard(props.assetId)
    attachments.value = await listAssetAttachments(props.assetId)
    timeline.value = await getAssetTimeline(props.assetId)
  } catch (e) {
    if ((e as ApiError).status === 404) notFound.value = true
  } finally {
    loading.value = false
  }
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
    <NAlert v-if="notFound" type="error">资产卡不存在</NAlert>
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
      <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20pxpx">财务信息区</div>
      <p>原值:{{ card.original_value ?? '—' }} 元;资金来源:{{ card.funding_source ?? '—' }};入账凭证号:{{ card.voucher_no ?? '未回填' }}</p>
      <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20pxpx">使用信息区</div>
      <p>状态:{{ card.status }};管理部门:{{ card.manage_dept ?? '—' }};使用部门:{{ card.use_dept ?? '—' }};保管人:{{ card.custodian_name ?? '—' }}</p>
      <p>校区:{{ card.campus ?? '—' }};楼栋:{{ card.building ?? '—' }};房间:{{ card.room_name ?? '—' }};领用状态:{{ card.borrow_status }}</p>
      <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20pxpx">特性信息区</div>
      <p>{{ card.attributes ? JSON.stringify(card.attributes) : '无特性字段' }}</p>
      <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20pxpx">校内扩展区(不同步)</div>
      <p>{{ card.ext ? JSON.stringify(card.ext) : '无扩展字段' }}</p>
      <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20pxpx">附件与影像归档</div>
      <NSpace style="margin-bottom: 12px">
        <NSelect v-model:value="fileType" :options="fileTypeOptions" style="width: 120px" />
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
      <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20pxpx">履历时间轴</div>
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
