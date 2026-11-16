<script setup lang="ts">
import {
  NAlert, NButton, NDataTable, NSpace,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import { getSyncPool, unselectForSync } from '@/api/asset'
import type { SyncPool, SyncPoolItem } from '@/api/asset'

// 学校资产管理系统一期第 2 批:待同步池(#87~#90)。
// 清单、件数、总价值、勾选人、勾选时间,按勾选批次分组展示;
// 未执行同步前可随时取消勾选。生成同步批次与导出/回填在 B5。
// 清单、件数、总价值、勾选人、勾选时间,按勾选批次分组展示。

const router = useRouter()

const loading = ref(false)
const forbidden = ref(false)
const pool = ref<SyncPool>({ items: [], total: 0, total_value: 0, groups: {} })
const resultMsg = ref('')

const groupRows = computed(() => Object.entries(pool.value.groups).map(([batch, g]) => ({
  batch_no: batch, count: g.count, total_value: g.total_value,
})))
const groupKey = (r: { batch_no: string }): string => r.batch_no

async function load() {
  loading.value = true
  forbidden.value = false
  try {
    pool.value = await getSyncPool()
  } catch (e) {
    if ((e as ApiError).status === 403) forbidden.value = true
  } finally {
    loading.value = false
  }
}

async function doUnselect(assetId: number, assetCode: string) {
  const res = await unselectForSync([assetId])
  resultMsg.value = res.succeeded.length
    ? `${assetCode} 已取消勾选,回到未同步`
    : `取消失败:${res.failed.map((f) => f.reason).join('；')}`
  await load()
}

onMounted(load)
</script>

<template>
  <div class="ios-page">
    <h1 class="ios-title">待同步池</h1>
    <NAlert type="info" style="margin-bottom: 12px">
      所有已勾选资产汇入待同步池;未执行同步前可随时取消勾选,状态回到未同步,
      不影响校内台账,不产生上报记录。下一步去“同步执行”页:先校验、再勾选确认生成批次、导出官方模板报送,最后把官方编号回填回来。
    </NAlert>
    <NSpace style="margin-bottom: 12px">
      <NButton type="primary" @click="router.push({ name: 'asset-sync' })">去同步执行</NButton>
      <NButton @click="router.push({ name: 'asset-ledger' })">去资产台账勾选更多</NButton>
    </NSpace>
    <NAlert v-if="forbidden" type="error" style="margin-bottom: 12px">权限不足</NAlert>
    <NAlert v-if="resultMsg" type="success" style="margin-bottom: 12px">{{ resultMsg }}</NAlert>
    <p v-if="!loading && pool.total === 0">池子还是空的:先去资产台账勾选要上报的资产,勾选后会出现在这里;入库默认是未同步,不会自动进池。</p>
    <div class="ios-card" style="margin-top: 16px">
      <div class="ios-card-body">
    <p>共 {{ pool.total }} 件,总价值 {{ pool.total_value }} 元</p>
    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 0px">按勾选批次分组</div>
    <NDataTable :bordered="false" :single-line="false"
      :columns="[
        { title: '勾选批次号', key: 'batch_no' },
        { title: '件数', key: 'count', width: 90 },
        { title: '总价值(元)', key: 'total_value', width: 140 },
      ]"
      :data="groupRows" :row-key="groupKey"
    />
    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20px">待同步清单</div>
    <NDataTable :bordered="false" :single-line="false"
      :columns="[
        { title: '资产编号', key: 'asset_code', width: 150 },
        { title: '名称', key: 'name' },
        { title: '分类', key: 'category_code', width: 100 },
        { title: '管理部门', key: 'manage_dept', width: 100 },
        { title: '原值(元)', key: 'original_value', width: 100 },
        { title: '勾选批次', key: 'selection_batch_no', width: 150 },
        { title: '勾选时间', key: 'selected_at', width: 180 },
      ]"
      :data="pool.items" :loading="loading" :row-key="(r: SyncPoolItem) => r.asset_id"
    />
    <NSpace style="margin-top: 8px">
      <NButton
        v-for="item in pool.items" :key="item.asset_id" size="small"
        @click="doUnselect(item.asset_id, item.asset_code)"
      >取消勾选 {{ item.asset_code }}</NButton>
    </NSpace>
      </div>
    </div>
  </div>
</template>
