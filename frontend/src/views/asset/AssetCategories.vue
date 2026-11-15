<script setup lang="ts">
import {
  NAlert, NDataTable, NEmpty, NSelect, NSpace, NText,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import { listAssetCategories } from '@/api/asset'
import type { AssetCategory } from '@/api/asset'

// 学校资产管理系统一期地基批:资产分类字典只读查看页(#16)。
// 只读展示即可,维护(财务科目对照、校内标签)与复杂页面留给 B2。
// 上报分类(GB/T 14885-2022)代码与名称已锁定,学校不得自行改动。

const loading = ref(false)
const forbidden = ref(false)
const categories = ref<AssetCategory[]>([])
const levelFilter = ref<number>(-1)

const levelOptions = [
  { label: '全部级别', value: -1 },
  { label: '一级', value: 1 },
  { label: '二级', value: 2 },
  { label: '三级', value: 3 },
  { label: '四级', value: 4 },
]

const filtered = computed(() => {
  const rows = levelFilter.value === -1
    ? categories.value
    : categories.value.filter((c) => c.level === levelFilter.value)
  return [...rows].sort((a, b) => a.code.localeCompare(b.code))
})

const columns = [
  { title: '分类代码', key: 'code', width: 140 },
  { title: '分类名称', key: 'name' },
  {
    title: '级别',
    key: 'level',
    width: 80,
    render: (row: AssetCategory) => `${row.level}级`,
  },
  { title: '上级代码', key: 'parent_code', width: 110, render: (row: AssetCategory) => row.parent_code ?? '—' },
  {
    title: '上报分类',
    key: 'is_reportable',
    width: 100,
    render: (row: AssetCategory) => (row.is_reportable ? '是(已锁定)' : '校内标签'),
  },
  {
    title: '状态',
    key: 'is_active',
    width: 80,
    render: (row: AssetCategory) => (row.is_active ? '启用' : '停用'),
  },
]

async function load() {
  loading.value = true
  forbidden.value = false
  try {
    categories.value = await listAssetCategories()
  } catch (e) {
    if ((e as ApiError).status === 403) forbidden.value = true
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="ios-page">
    <h1 class="ios-title">资产分类字典</h1>
    <NAlert type="info" style="margin-bottom: 12px">
      执行 GB/T 14885-2022 六大类;上报分类代码与名称已锁定,学校不得自行改动。
      二级及以下分类为示例种子,须以学校当期官方模板核定后冻结为 V1 版。
    </NAlert>
    <div class="ios-card" style="margin-top: 16px">
      <div class="ios-card-body">
    <NSpace style="margin-bottom: 12px">
      <NText>级别筛选</NText>
      <NSelect
        v-model:value="levelFilter"
        :options="levelOptions"
        style="width: 140px"
      />
    </NSpace>
    <NAlert v-if="forbidden" type="error">权限不足,请联系系统管理员</NAlert>
    <NEmpty v-else-if="!loading && filtered.length === 0" description="暂无分类数据" />
    <NDataTable :bordered="false" :single-line="false"
      v-else
      :loading="loading"
      :columns="columns"
      :data="filtered"
      :pagination="{ pageSize: 20 }"
    />
      </div>
    </div>
  </div>
</template>
