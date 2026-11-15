<script setup lang="ts">
import {
  NAlert, NButton, NInput, NSpace,
} from 'naive-ui'
import { ref } from 'vue'
import { assetLabelQrUrl, listAssetLabels, printAssetLabels } from '@/api/asset'
import type { AssetLabel } from '@/api/asset'

// 学校资产管理系统一期第 2 批:二维码标签打印(#28)。
// 建卡即生成二维码标签(含名称、编号、保管部门);批量打印、补打用
// 浏览器打印友好页面(复用课表打印页的 window.print 模式),不引入
// 新的打印服务。复核补:标签卡上的二维码图由后端现场生成
// (GET /assets/{id}/label/qr,标签码编成的 QR-SVG);此前只印标签码
// 文本、无二维码图形。未接路由(由收尾批统一接线)。

const idsText = ref('')
const labels = ref<AssetLabel[]>([])
const loading = ref(false)
const resultMsg = ref('')

async function load() {
  const ids = idsText.value.split(/[,，\s]+/).map((s) => Number(s)).filter((n) => n > 0)
  if (ids.length === 0) return
  loading.value = true
  try {
    labels.value = await listAssetLabels(ids)
  } finally {
    loading.value = false
  }
}

async function doPrint() {
  if (labels.value.length === 0) return
  await printAssetLabels(labels.value.map((l) => l.asset_id))
  resultMsg.value = `已记录打印 ${labels.value.length} 张标签`
  window.print()
}
</script>

<template>
  <div class="ios-page">
    <h1 class="ios-title">二维码标签打印</h1>
    <NAlert type="info" style="margin-bottom: 12px">
      标签含名称、编号、保管部门;建卡即生成标签码(编号 + 校验位)。
      打印用浏览器打印,打印动作记审计;单件补打在资产卡页操作。
    </NAlert>
    <NAlert v-if="resultMsg" type="success" style="margin-bottom: 12px">{{ resultMsg }}</NAlert>
    <div class="ios-card" style="margin-top: 16px">
      <div class="ios-card-body">
    <NSpace class="no-print" style="margin-bottom: 12px">
      <NInput v-model:value="idsText" placeholder="资产 id,逗号分隔(如 1,2,3)" style="width: 280px" />
      <NButton type="primary" :loading="loading" @click="load">加载标签</NButton>
      <NButton :disabled="labels.length === 0" @click="doPrint">批量打印</NButton>
    </NSpace>
      </div>
    </div>
    <div class="label-sheet">
      <div v-for="l in labels" :key="l.asset_id" class="label-card">
        <img class="label-qr" :src="assetLabelQrUrl(l.asset_id)" alt="二维码" />
        <div class="label-name">{{ l.name }}</div>
        <div class="label-code">{{ l.asset_code }}</div>
        <div class="label-dept">{{ l.manage_dept ?? '未分部门' }}</div>
        <div class="label-tag">{{ l.label_code }} {{ l.valid ? '校验通过' : '校验失败' }}</div>
      </div>
      <p v-if="labels.length === 0">请先输入资产 id 加载标签。</p>
    </div>
  </div>
</template>

<style scoped>
.label-sheet { display: flex; flex-wrap: wrap; gap: 12px; }
.label-qr { max-width: 160px; max-height: 160px; }
.label-card {
  width: 240px; border: 1px solid #333; border-radius: 6px;
  padding: 12px; text-align: center;
}
.label-name { font-size: 16px; font-weight: bold; }
.label-code { font-size: 14px; margin-top: 6px; }
.label-dept { font-size: 13px; color: rgba(60, 60, 67, 0.6); margin-top: 4px; }
.label-tag { font-size: 12px; color: rgba(60, 60, 67, 0.6); margin-top: 4px; }
@media print {
  .no-print { display: none !important; }
  .label-card { page-break-inside: avoid; }
}
</style>
