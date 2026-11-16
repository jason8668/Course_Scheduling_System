<script setup lang="ts">
import {
  NAlert, NButton, NDataTable, NSpace,
} from 'naive-ui'
import { ref } from 'vue'
import { assetLabelQrUrl, listAssetLabels, printAssetLabels } from '@/api/asset'
import type { AssetCard, AssetLabel } from '@/api/asset'
import AssetPicker from '@/components/AssetPicker.vue'

// 学校资产管理系统一期第 2 批:二维码标签打印(#28)。
// 建卡即生成二维码标签(含名称、编号、保管部门);批量打印、补打用
// 浏览器打印友好页面(复用课表打印页的 window.print 模式),不引入
// 新的打印服务。复核补:标签卡上的二维码图由后端现场生成
// (GET /assets/{id}/label/qr,标签码编成的 QR-SVG);此前只印标签码
// 文本、无二维码图形。
// 之前要手填内部资产 id(用户不知道 id 是几号),现改为按编号/名称搜索加入清单。

const pickedId = ref<number | null>(null)
const pickedCard = ref<AssetCard | null>(null)
const chosen = ref<AssetCard[]>([])
const labels = ref<AssetLabel[]>([])
const loading = ref(false)
const resultMsg = ref('')

function onPick(card: AssetCard) {
  pickedCard.value = card
}

function addChosen() {
  if (!pickedCard.value) return
  if (!chosen.value.some((c) => c.id === pickedCard.value!.id)) {
    chosen.value.push(pickedCard.value)
  }
  pickedId.value = null
  pickedCard.value = null
}

function removeChosen(id: number) {
  chosen.value = chosen.value.filter((c) => c.id !== id)
}

async function load() {
  if (chosen.value.length === 0) return
  loading.value = true
  try {
    labels.value = await listAssetLabels(chosen.value.map((c) => c.id))
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
      先在下方按编号或名称搜索资产、加入打印清单,再点“加载标签”核对后批量打印。
    </NAlert>
    <NAlert v-if="resultMsg" type="success" style="margin-bottom: 12px">{{ resultMsg }}</NAlert>
    <div class="ios-card" style="margin-top: 16px">
      <div class="ios-card-body">
    <NSpace class="no-print" style="margin-bottom: 12px">
      <AssetPicker v-model="pickedId" style="width: 320px" @select="onPick" />
      <NButton :disabled="!pickedCard" @click="addChosen">加入打印清单</NButton>
      <NButton type="primary" :loading="loading" :disabled="chosen.length === 0" @click="load">加载标签</NButton>
      <NButton :disabled="labels.length === 0" @click="doPrint">批量打印</NButton>
    </NSpace>
    <p v-if="chosen.length === 0">还没有加入任何资产:先在上方按编号或名称搜索,选中后点“加入打印清单”;不知道编号就去资产台账按名称找。</p>
    <NDataTable v-else :bordered="false" :single-line="false"
      :columns="[
        { title: '资产编号', key: 'asset_code', width: 160 },
        { title: '名称', key: 'name' },
        { title: '管理部门', key: 'manage_dept', width: 120 },
      ]"
      :data="chosen" :row-key="(r: AssetCard) => r.id"
    />
    <NSpace v-if="chosen.length > 0" style="margin-top: 8px">
      <NButton v-for="c in chosen" :key="c.id" size="small" @click="removeChosen(c.id)">移除 {{ c.asset_code }}</NButton>
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
      <p v-if="labels.length === 0">还没有加载标签。</p>
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
