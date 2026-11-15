<script setup lang="ts">
import {
  NAlert, NButton, NDataTable, NInput, NSpace,
} from 'naive-ui'
import { onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import {
  closeInventoryPlan, computeInventoryDiffs, createInventoryPlan,
  createInventoryTask, getInventoryPlan, getInventoryReport, listInventoryDifferences,
  listInventoryPlans, resolveInventoryDifference, scanInventory,
  unlabelledInventory,
} from '@/api/asset'
import type {
  InventoryDifference, InventoryPlan, InventoryReport,
} from '@/api/asset'

// 学校资产管理系统一期第 4 批:盘点清查(#48/#49/#51/#52)。
// 未接路由(由收尾批统一接线)。范围外扫码明确提示、不静默计入;
// 盘点结果不自动同步到官方,报告只标注涉及已同步资产的差异。

const resultMsg = ref('')
const errorMsg = ref('')

const planName = ref('')
const planType = ref('全校盘点')
const plans = ref<InventoryPlan[]>([])
const planId = ref('')
const assigneeId = ref('')
const scopeDept = ref('')
const scopeRoom = ref('')
const dueAt = ref('')
const taskId = ref('')
const labelCode = ref('')
const scanRoom = ref('')
const unlabelledName = ref('')
const unlabelledPhoto = ref('')
const diffs = ref<InventoryDifference[]>([])
const resolveId = ref('')
const resolveAction = ref('shortage')
const resolveNote = ref('')
const resolveName = ref('')
const resolveCategory = ref('')
const report = ref<InventoryReport | null>(null)

async function load() {
  try {
    plans.value = await listInventoryPlans()
  } catch (e) {
    errorMsg.value = (e as ApiError).detail ?? '加载失败'
  }
}

function showError(e: unknown) {
  errorMsg.value = (e as ApiError).detail ?? '操作失败'
  resultMsg.value = ''
}

async function doCreatePlan() {
  try {
    const row = await createInventoryPlan({ name: planName.value, plan_type: planType.value })
    resultMsg.value = `盘点方案 ${row.plan_no} 已创建`
    errorMsg.value = ''
    await load()
  } catch (e) { showError(e) }
}

async function doCreateTask() {
  try {
    const row = await createInventoryTask(Number(planId.value), {
      assignee_id: Number(assigneeId.value),
      scope_dept: scopeDept.value || undefined,
      scope_room_name: scopeRoom.value || undefined, due_at: dueAt.value,
    })
    resultMsg.value = `盘点任务已分派给 ${row.assignee_name},截止 ${row.due_at ?? ''}`
    errorMsg.value = ''
  } catch (e) { showError(e) }
}

async function doScan() {
  try {
    const out = await scanInventory(Number(taskId.value), {
      label_code: labelCode.value, room_name: scanRoom.value || undefined,
    })
    resultMsg.value = out.in_scope ? out.message : `范围外未计入:${out.message}`
    errorMsg.value = ''
  } catch (e) { showError(e) }
}

async function doUnlabelled() {
  try {
    const row = await unlabelledInventory(Number(taskId.value), {
      name: unlabelledName.value, photo_url: unlabelledPhoto.value || undefined,
      room_name: scanRoom.value || undefined,
    })
    resultMsg.value = `未贴标资产已补录,待核实(记录 ${row.id})`
    errorMsg.value = ''
  } catch (e) { showError(e) }
}

async function doComputeDiffs() {
  try {
    const out = await computeInventoryDiffs(Number(taskId.value))
    resultMsg.value = `差异比对完成:正常 ${out.counts['正常'] ?? 0}、盘亏 ${out.counts['盘亏'] ?? 0}、盘盈 ${out.counts['盘盈'] ?? 0}、位置不符 ${out.counts['位置不符'] ?? 0}、保管人不符 ${out.counts['保管人不符'] ?? 0}`
    errorMsg.value = ''
    await loadDiffs()
  } catch (e) { showError(e) }
}

async function loadDiffs() {
  try {
    diffs.value = await listInventoryDifferences(Number(planId.value))
  } catch (e) { showError(e) }
}

async function doResolve() {
  try {
    const row = await resolveInventoryDifference(Number(resolveId.value), {
      action: resolveAction.value as 'shortage' | 'surplus_create' | 'correct_location' | 'correct_custodian' | 'note',
      resolution: resolveNote.value,
      name: resolveName.value || undefined,
      category_code: resolveCategory.value || undefined,
    })
    resultMsg.value = `差异 ${row.id} 已处理:${row.resolution}`
    errorMsg.value = ''
    await loadDiffs()
  } catch (e) { showError(e) }
}

async function doClose() {
  try {
    const row = await closeInventoryPlan(Number(planId.value))
    resultMsg.value = `盘点方案 ${row.plan_no} 已由领导确认关闭`
    errorMsg.value = ''
    await load()
  } catch (e) { showError(e) }
}

async function doReport() {
  try {
    report.value = await getInventoryReport(Number(planId.value))
    errorMsg.value = ''
  } catch (e) { showError(e) }
}

async function doShowPlan() {
  try {
    const row = await getInventoryPlan(Number(planId.value))
    resultMsg.value = `方案 ${row.plan_no} 状态:${row.status},任务 ${row.tasks.length} 个`
    errorMsg.value = ''
    await loadDiffs()
  } catch (e) { showError(e) }
}

onMounted(load)
</script>

<template>
  <div class="ios-page">
    <h1 class="ios-title">盘点清查</h1>
    <NAlert v-if="errorMsg" type="error" style="margin-bottom: 12px">{{ errorMsg }}</NAlert>
    <NAlert v-if="resultMsg" type="success" style="margin-bottom: 12px">{{ resultMsg }}</NAlert>
    <div class="ios-card" style="margin-top: 16px">
      <div class="ios-card-body">

    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 0px">盘点方案与任务拆分</div>
    <NSpace style="margin-bottom: 12px">
      <NInput v-model:value="planName" placeholder="方案名称" style="width: 180px" />
      <NInput v-model:value="planType" placeholder="全校盘点/抽盘/专项盘点" style="width: 180px" />
      <NButton type="primary" @click="doCreatePlan">创建盘点方案</NButton>
    </NSpace>
    <NDataTable :bordered="false" :single-line="false"
      :columns="[
        { title: '方案号', key: 'plan_no' },
        { title: '名称', key: 'name' },
        { title: '类型', key: 'plan_type' },
        { title: '状态', key: 'status' },
      ]"
      :data="plans" :row-key="(r: InventoryPlan) => r.id"
    />
    <NSpace style="margin-top: 8px; margin-bottom: 12px">
      <NInput v-model:value="planId" placeholder="方案 id" style="width: 100px" />
      <NInput v-model:value="assigneeId" placeholder="盘点人 id" style="width: 100px" />
      <NInput v-model:value="scopeDept" placeholder="范围部门" style="width: 130px" />
      <NInput v-model:value="scopeRoom" placeholder="范围房间" style="width: 130px" />
      <NInput v-model:value="dueAt" placeholder="截止时间" style="width: 180px" />
      <NButton @click="doCreateTask">拆分任务分派到人</NButton>
      <NButton @click="doShowPlan">查看方案与差异</NButton>
    </NSpace>

    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20pxpx">手机扫码盘点</div>
    <NSpace style="margin-bottom: 12px">
      <NInput v-model:value="taskId" placeholder="任务 id" style="width: 100px" />
      <NInput v-model:value="labelCode" placeholder="标签码(扫码)" style="width: 200px" />
      <NInput v-model:value="scanRoom" placeholder="实盘房间" style="width: 140px" />
      <NButton type="primary" @click="doScan">扫码盘点</NButton>
      <NButton @click="doComputeDiffs">五类差异自动比对</NButton>
    </NSpace>
    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20pxpx">未贴标资产现场补录拍照</div>
    <NSpace style="margin-bottom: 12px">
      <NInput v-model:value="unlabelledName" placeholder="补录资产名称" style="width: 180px" />
      <NInput v-model:value="unlabelledPhoto" placeholder="现场照片地址" style="width: 200px" />
      <NButton @click="doUnlabelled">补录进待核实清单</NButton>
    </NSpace>

    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20pxpx">五类差异清单与处理</div>
    <NDataTable :bordered="false" :single-line="false"
      :columns="[
        { title: '差异', key: 'diff_type' },
        { title: '资产编号', key: 'asset_code' },
        { title: '资产名称', key: 'asset_name' },
        { title: '状态', key: 'status' },
        { title: '处理说明', key: 'resolution' },
      ]"
      :data="diffs" :row-key="(r: InventoryDifference) => r.id"
    />
    <NSpace style="margin-top: 8px; margin-bottom: 12px">
      <NInput v-model:value="resolveId" placeholder="差异 id" style="width: 100px" />
      <NInput v-model:value="resolveAction" placeholder="shortage/surplus_create/correct_location/correct_custodian/note" style="width: 320px" />
      <NInput v-model:value="resolveNote" placeholder="处理说明/责任说明" style="width: 180px" />
      <NInput v-model:value="resolveName" placeholder="盘盈补建卡名称" style="width: 140px" />
      <NInput v-model:value="resolveCategory" placeholder="盘盈分类代码" style="width: 120px" />
      <NButton @click="doResolve">处理差异</NButton>
    </NSpace>
    <p>盘亏查责任、盘盈补建卡(走盘盈补记入库)、位置/保管人不符直接更正并留痕;差异未处理完不得关闭盘点。</p>

    <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20pxpx">盘点报告与关闭</div>
    <NSpace style="margin-bottom: 12px">
      <NButton @click="doReport">查看盘点报告</NButton>
      <NButton type="primary" @click="doClose">领导确认关闭盘点</NButton>
    </NSpace>
    <p v-if="report">应盘 {{ report.total_expected }} 件,实盘 {{ report.total_scanned }} 件,未处理 {{ report.unresolved }} 条;涉及已同步资产 {{ report.synced_differences.length }} 条(只标注,盘点结果不自动同步到官方)。</p>
      </div>
    </div>
  </div>
</template>
