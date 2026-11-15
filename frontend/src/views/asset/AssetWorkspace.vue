<script setup lang="ts">
import {
  NAlert, NButton, NDataTable, NSpace,
} from 'naive-ui'
import { onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import {
  createReturn, listMyAssets, listMyReminders, listMyTodos,
  markReminderRead, reportRepairFromWorkspace,
} from '@/api/asset'
import type { AssetCard, AssetReminder, TodoItem } from '@/api/asset'

// 学校资产管理系统一期第 3 批:个人工作台(#1/#2/#3)。
// 未接路由(由收尾批统一接线)。待办紧急程度:逾期 > 当天到期 > 待审批 > 其他。

const errorMsg = ref('')
const resultMsg = ref('')
const todos = ref<TodoItem[]>([])
const myAssets = ref<AssetCard[]>([])
const reminders = ref<AssetReminder[]>([])

async function load() {
  try {
    todos.value = await listMyTodos()
    myAssets.value = (await listMyAssets()).items
    reminders.value = await listMyReminders()
  } catch (e) {
    errorMsg.value = (e as ApiError).detail ?? '加载失败'
  }
}

async function doReportRepair(assetId: number) {
  try {
    const row = await reportRepairFromWorkspace(assetId, '工作台报修')
    resultMsg.value = `维修占位单 ${row.doc_no} 已创建(工单流程由 B4 实现)`
    errorMsg.value = ''
  } catch (e) {
    errorMsg.value = (e as ApiError).detail ?? '报修失败'
  }
}

async function doReturn(assetId: number) {
  try {
    const row = await createReturn({ asset_id: assetId })
    resultMsg.value = `归还单 ${row.doc_no} 已创建,请到领用借用页扫码验收`
    errorMsg.value = ''
  } catch (e) {
    errorMsg.value = (e as ApiError).detail ?? '归还失败'
  }
}

async function doRead(id: number) {
  await markReminderRead(id)
  await load()
}

onMounted(load)
</script>

<template>
  <div class="ios-page">
    <h1 class="ios-title">我的工作台</h1>
    <NAlert v-if="errorMsg" type="error" style="margin-bottom: 12px">{{ errorMsg }}</NAlert>
    <NAlert v-if="resultMsg" type="success" style="margin-bottom: 12px">{{ resultMsg }}</NAlert>
    <div class="ios-card" style="margin-top: 16px">
      <div class="ios-card-body">

    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 0px">我的待办</div>
    <p v-if="todos.length === 0">暂无待办</p>
    <NDataTable :bordered="false" :single-line="false"
      v-else
      :columns="[
        { title: '类型', key: 'kind', width: 120 },
        { title: '内容', key: 'title' },
        { title: '紧急程度', key: 'urgency', width: 100 },
      ]"
      :data="todos" :row-key="(r: TodoItem) => `${r.kind}-${r.target_id}`"
    />

    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20pxpx">我的资产</div>
    <p v-if="myAssets.length === 0">名下暂无资产</p>
    <NDataTable :bordered="false" :single-line="false"
      v-else
      :columns="[
        { title: '编号', key: 'asset_code' },
        { title: '名称', key: 'name' },
        { title: '状态', key: 'status' },
        { title: '保管人', key: 'custodian_name' },
      ]"
      :data="myAssets" :row-key="(r: AssetCard) => r.id"
    />
    <NSpace style="margin-top: 8px">
      <template v-for="a in myAssets" :key="a.id">
        <NButton size="small" @click="doReportRepair(a.id)">报修 {{ a.asset_code }}</NButton>
        <NButton size="small" @click="doReturn(a.id)">归还 {{ a.asset_code }}</NButton>
      </template>
    </NSpace>

    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20pxpx">消息与提醒中心</div>
    <p v-if="reminders.length === 0">暂无提醒</p>
    <NDataTable :bordered="false" :single-line="false"
      v-else
      :columns="[
        { title: '类型', key: 'kind', width: 100 },
        { title: '标题', key: 'title' },
        { title: '级别', key: 'level', width: 80 },
        { title: '已读', key: 'is_read', width: 70, render: (r: AssetReminder) => r.is_read ? '已读' : '未读' },
      ]"
      :data="reminders" :row-key="(r: AssetReminder) => r.id"
    />
    <NSpace style="margin-top: 8px">
      <NButton v-for="r in reminders.filter((i) => !i.is_read)" :key="r.id" size="small" @click="doRead(r.id)">标为已读 {{ r.title }}</NButton>
    </NSpace>
      </div>
    </div>
  </div>
</template>
