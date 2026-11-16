<script setup lang="ts">
import { NSelect } from 'naive-ui'
import { ref } from 'vue'
import { searchAssets } from '@/api/asset'
import type { AssetCard } from '@/api/asset'

// 按编号/名称搜资产的远程下拉:替代手填内部资产 id(用户不知道 id 是几号)。
// v-model 为资产 id;选中后同时 emit('select', 资产卡片)。
// 搜不到时下拉为空,文案会提示去台账核对编号。
const props = defineProps<{
  modelValue: number | null
  placeholder?: string
  disabled?: boolean
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: number | null): void
  (e: 'select', v: AssetCard): void
}>()

const options = ref<{ label: string; value: number }[]>([])
const loading = ref(false)
const cache = new Map<number, AssetCard>()

async function onSearch(q: string) {
  if (!q) {
    options.value = []
    return
  }
  loading.value = true
  try {
    const data = await searchAssets({ q, limit: 20 })
    options.value = data.items.map((a) => ({
      label: `${a.asset_code} ${a.name}（${a.status}·${a.custodian_name ?? '未分保管人'}）`,
      value: a.id,
    }))
    data.items.forEach((a) => cache.set(a.id, a))
  } finally {
    loading.value = false
  }
}

function onChange(v: number | null) {
  emit('update:modelValue', v)
  if (v !== null && cache.has(v)) emit('select', cache.get(v) as AssetCard)
}
</script>

<template>
  <NSelect
    :value="props.modelValue" :options="options" :loading="loading"
    filterable remote clearable :disabled="props.disabled"
    :placeholder="props.placeholder ?? '输入资产编号或名称搜索，如 打印机 / ZC2026…'"
    @search="onSearch" @update:value="onChange"
  />
</template>
