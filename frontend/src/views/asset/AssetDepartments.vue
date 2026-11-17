<script setup lang="ts">
import {
  NAlert, NButton, NDataTable, NInput, NPopconfirm, NSelect, NSpace,
} from 'naive-ui'
import { onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import { apiDelete, apiGet, request } from '@/api/client'

// 学校资产管理系统一期补半成品 #76:部门字典管理页。
// 部门原先是资产卡上的自由字符串,同义写法(“教务处”vs“教务”)会漏数;
// 本页维护部门字典(新增/改名/停用/删除),并处理“待认领”区:
// 字典里没有、但资产卡上仍有原字符串值的部门,管理员可新建字典认领
// 或并入已有部门。删除仅当无资产引用时可删(后端校验)。

interface AssetDepartment {
  id: number
  name: string
  code: string | null
  parent_id: number | null
  parent_name: string | null
  is_active: boolean
  manage_count: number
  use_count: number
  asset_count: number
}

interface UnclaimedDepartment {
  name: string
  manage_count: number
  use_count: number
  total_count: number
}

const loading = ref(false)
const forbidden = ref(false)
const resultMsg = ref('')
const departments = ref<AssetDepartment[]>([])
const unclaimed = ref<UnclaimedDepartment[]>([])

const newName = ref('')
const newCode = ref('')
// 上级部门用 -1 表示“无上级”:naive-ui NSelect 的选项值不接受 null。
const newParentId = ref(-1)

const editingId = ref<number | null>(null)
const editName = ref('')
const editCode = ref('')
const editParentId = ref(-1)
const editActiveOpt = ref<'active' | 'inactive'>('active')

const claimTarget = ref<Record<string, number | null>>({})

const parentOptions = () => [
  { label: '无上级(顶级部门)', value: -1 },
  ...departments.value.map((d) => ({ label: d.name, value: d.id })),
]

const columns = [
  { title: '部门名称', key: 'name' },
  { title: '代码', key: 'code', width: 100, render: (r: AssetDepartment) => r.code ?? '—' },
  { title: '上级部门', key: 'parent_name', width: 120, render: (r: AssetDepartment) => r.parent_name ?? '—' },
  {
    title: '状态', key: 'is_active', width: 80,
    render: (r: AssetDepartment) => (r.is_active ? '启用' : '停用'),
  },
  { title: '管理部门资产', key: 'manage_count', width: 110 },
  { title: '使用部门资产', key: 'use_count', width: 110 },
  { title: '合计', key: 'asset_count', width: 80 },
]

async function load() {
  loading.value = true
  forbidden.value = false
  try {
    departments.value = await apiGet<AssetDepartment[]>('/asset/departments')
    unclaimed.value = await apiGet<UnclaimedDepartment[]>('/asset/departments/unclaimed')
  } catch (e) {
    if ((e as ApiError).status === 403) forbidden.value = true
  } finally {
    loading.value = false
  }
}

async function doCreate() {
  if (!newName.value.trim()) return
  const row = await request<AssetDepartment>('POST', '/asset/departments', {
    name: newName.value.trim(),
    code: newCode.value.trim() || undefined,
    parent_id: newParentId.value === -1 ? null : newParentId.value,
  })
  resultMsg.value = `部门 ${row.name} 已新增`
  newName.value = ''
  newCode.value = ''
  newParentId.value = -1
  await load()
}

function startEdit(row: AssetDepartment) {
  editingId.value = row.id
  editName.value = row.name
  editCode.value = row.code ?? ''
  editParentId.value = row.parent_id ?? -1
  editActiveOpt.value = row.is_active ? 'active' : 'inactive'
}

async function doSaveEdit() {
  if (editingId.value === null || !editName.value.trim()) return
  const row = await request<AssetDepartment>(
    'PATCH', `/asset/departments/${editingId.value}`, {
      name: editName.value.trim(),
      code: editCode.value.trim() || null,
      parent_id: editParentId.value === -1 ? null : editParentId.value,
      is_active: editActiveOpt.value === 'active',
    },
  )
  resultMsg.value = `部门 ${row.name} 已保存(改名已同步改写资产卡上的旧部门名)`
  editingId.value = null
  await load()
}

async function doToggleActive(row: AssetDepartment) {
  await request<AssetDepartment>('PATCH', `/asset/departments/${row.id}`, {
    is_active: !row.is_active,
  })
  resultMsg.value = `部门 ${row.name} 已${row.is_active ? '停用' : '启用'}`
  await load()
}

async function doDelete(row: AssetDepartment) {
  await apiDelete(`/asset/departments/${row.id}`)
  resultMsg.value = `部门 ${row.name} 已删除`
  await load()
}

async function doClaimIntoExisting(name: string) {
  const targetId = claimTarget.value[name]
  if (!targetId) return
  const res = await request<{
    department_name: string; updated_manage: number; updated_use: number
  }>('POST', `/asset/departments/${targetId}/claim`, { name, field: 'both' })
  resultMsg.value = `“${name}”已并入 ${res.department_name}`
    + `(管理部门 ${res.updated_manage} 件,使用部门 ${res.updated_use} 件)`
  await load()
}

async function doClaimAsNew(name: string) {
  const row = await request<AssetDepartment>('POST', '/asset/departments', { name })
  const res = await request<{
    updated_manage: number; updated_use: number
  }>('POST', `/asset/departments/${row.id}/claim`, { name, field: 'both' })
  resultMsg.value = `“${name}”已新建为字典部门并认领`
    + `(管理部门 ${res.updated_manage} 件,使用部门 ${res.updated_use} 件)`
  await load()
}

async function doReconcile() {
  const res = await request<{ updated_manage: number; updated_use: number }>(
    'POST', '/asset/departments/reconcile',
  )
  resultMsg.value = `重新对齐:管理部门 ${res.updated_manage} 件,`
    + `使用部门 ${res.updated_use} 件已按字典名补上关联`
  await load()
}

onMounted(load)
</script>

<template>
  <div class="ios-page">
    <h1 class="ios-title">部门字典</h1>
    <NAlert type="info" style="margin-bottom: 12px">
      组织架构四级(校区/楼栋/部门/房间)中的部门一级:资产卡的管理部门与使用部门
      以这里为准,不要再手填自由文本,同义写法(“教务处”vs“教务”)会漏数。
      改名会自动同步改写资产卡上的旧部门名;仍被资产引用的部门不可删。
    </NAlert>
    <NAlert v-if="forbidden" type="error" style="margin-bottom: 12px">权限不足</NAlert>
    <NAlert v-if="resultMsg" type="success" style="margin-bottom: 12px">{{ resultMsg }}</NAlert>
    <div class="ios-card" style="margin-top: 16px">
      <div class="ios-card-body">
        <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 0px">新增部门</div>
        <NSpace style="margin-bottom: 12px">
          <NInput v-model:value="newName" placeholder="部门名称(必填,如 教务处)" style="width: 180px" />
          <NInput v-model:value="newCode" placeholder="部门代码(可选,如 JW01)" style="width: 160px" />
          <NSelect v-model:value="newParentId" :options="parentOptions()" placeholder="上级部门" style="width: 180px" />
          <NButton type="primary" :disabled="!newName.trim()" @click="doCreate">新增部门</NButton>
          <NButton @click="doReconcile">重新对齐</NButton>
        </NSpace>
        <p>“重新对齐”:资产卡上部门字符串与字典名一致、但关联为空的,按字典名补上关联(入库建卡只填了部门名时用)。</p>

        <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20px">部门列表</div>
        <NDataTable :bordered="false" :single-line="false"
          :columns="columns" :data="departments" :loading="loading"
          :row-key="(r: AssetDepartment) => r.id"
        />
        <NSpace style="margin: 8px 0 24px">
          <template v-for="d in departments" :key="d.id">
            <NButton size="small" @click="startEdit(d)">改名 {{ d.name }}</NButton>
            <NButton size="small" @click="doToggleActive(d)">{{ d.is_active ? '停用' : '启用' }} {{ d.name }}</NButton>
            <NPopconfirm @positive-click="doDelete(d)">
              <template #trigger><NButton size="small">删除 {{ d.name }}</NButton></template>
              确认删除部门 {{ d.name }} 吗?仍被资产引用的部门不可删。
            </NPopconfirm>
          </template>
        </NSpace>
        <div v-if="editingId !== null" class="ios-card" style="margin-bottom: 12px">
          <div class="ios-card-body">
            <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 0px">改名 / 维护</div>
            <NSpace>
              <NInput v-model:value="editName" placeholder="部门名称" style="width: 180px" />
              <NInput v-model:value="editCode" placeholder="部门代码" style="width: 160px" />
              <NSelect v-model:value="editParentId" :options="parentOptions()" placeholder="上级部门" style="width: 180px" />
              <NSelect
                v-model:value="editActiveOpt"
                :options="[{ label: '启用', value: 'active' }, { label: '停用', value: 'inactive' }]"
                style="width: 100px"
              />
              <NButton type="primary" :disabled="!editName.trim()" @click="doSaveEdit">保存</NButton>
              <NButton @click="editingId = null">取消</NButton>
            </NSpace>
          </div>
        </div>

        <div class="ios-section-title" style="padding: 0 0 6px; margin-top: 20px">待认领</div>
        <p>字典里没有、但资产卡上仍有原字符串值的部门:点“新建字典并认领”按原名建字典并关联,
          或选一个已有部门点“并入”,字符串口径会统一成字典名。</p>
        <p v-if="unclaimed.length === 0">暂无待认领部门:资产卡上的部门名都已在字典里。</p>
        <div v-else>
          <NDataTable :bordered="false" :single-line="false"
            :columns="[
              { title: '原部门名', key: 'name' },
              { title: '管理部门资产', key: 'manage_count', width: 120 },
              { title: '使用部门资产', key: 'use_count', width: 120 },
              { title: '合计', key: 'total_count', width: 80 },
            ]"
            :data="unclaimed" :row-key="(r: UnclaimedDepartment) => r.name"
          />
          <NSpace vertical style="margin-top: 8px">
            <NSpace v-for="u in unclaimed" :key="u.name">
              <span style="width: 120px">{{ u.name }}</span>
              <NSelect
                v-model:value="claimTarget[u.name]"
                :options="departments.map((d) => ({ label: d.name, value: d.id }))"
                placeholder="并入已有部门"
                style="width: 180px"
              />
              <NButton size="small" :disabled="!claimTarget[u.name]" @click="doClaimIntoExisting(u.name)">
                并入 {{ u.name }}
              </NButton>
              <NButton size="small" @click="doClaimAsNew(u.name)">新建字典并认领 {{ u.name }}</NButton>
            </NSpace>
          </NSpace>
        </div>
      </div>
    </div>
  </div>
</template>
