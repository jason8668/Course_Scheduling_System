<script setup lang="ts">
import {
  NButton, NCheckbox, NEmpty, NInput, NInputNumber, NModal, NPopconfirm, NSelect, NSpace, NText,
  useMessage,
} from 'naive-ui'
import { onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import {
  ROOM_TYPE_LABELS, createSubject, deleteSubject, listSubjects, updateSubject,
} from '@/api/basedata'
import type { RoomType, Subject } from '@/api/basedata'

const props = defineProps<{ semesterId: number }>()
const message = useMessage()

const items = ref<Subject[]>([])
const search = ref('')

const roomTypeOptions = (Object.keys(ROOM_TYPE_LABELS) as RoomType[]).map((t) => ({
  label: ROOM_TYPE_LABELS[t], value: t,
}))

async function reload() {
  items.value = await listSubjects(props.semesterId, search.value || undefined)
}
onMounted(reload)

const show = ref(false)
const editingId = ref<number | null>(null)
const form = ref<{
  name: string
  domain: string
  required_room_type: RoomType | null
  default_block_size: number
  is_major: boolean
}>({ name: '', domain: '', required_room_type: null, default_block_size: 1, is_major: false })

function openCreate() {
  editingId.value = null
  form.value = { name: '', domain: '', required_room_type: null, default_block_size: 1, is_major: false }
  show.value = true
}
function openEdit(s: Subject) {
  editingId.value = s.id
  form.value = {
    name: s.name, domain: s.domain ?? '',
    required_room_type: s.required_room_type, default_block_size: s.default_block_size,
    is_major: s.is_major,
  }
  show.value = true
}

async function save() {
  if (!form.value.name) {
    message.warning('请输入科目名称')
    return
  }
  const body = {
    name: form.value.name,
    domain: form.value.domain || null,
    required_room_type: form.value.required_room_type,
    default_block_size: form.value.default_block_size,
    is_major: form.value.is_major,
  }
  try {
    if (editingId.value) await updateSubject(editingId.value, body)
    else await createSubject(props.semesterId, body)
    show.value = false
    message.success('已储存')
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '储存失败')
  }
}

async function remove(s: Subject) {
  try {
    await deleteSubject(s.id)
    message.success('已删除')
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '删除失败')
  }
}
</script>

<template>
  <n-space vertical>
    <n-space>
      <n-input v-model:value="search" placeholder="搜寻科目名称" clearable style="width: 200px" @input="reload" />
      <n-button type="primary" round @click="openCreate">新增科目</n-button>
    </n-space>

    <div class="ios-card">
      <n-empty v-if="items.length === 0" description="尚无科目" style="padding: 24px 0" />
      <template v-else>
        <div v-for="s in items" :key="s.id" class="ios-row">
          <div class="ios-row-main">
            <span class="ios-row-title">{{ s.name }}</span>
            <span class="ios-row-sub" style="margin-left: 8px">
              {{ s.domain || '无领域' }}
              · 场地 {{ s.required_room_type ? ROOM_TYPE_LABELS[s.required_room_type] : '不限' }}
              · {{ s.default_block_size > 1 ? `${s.default_block_size} 连堂` : '一般' }}
            </span>
            <span v-if="s.is_major" class="ios-chip" style="margin-left: 8px" :data-testid="`sub-major-${s.name}`">主科</span>
          </div>
          <n-button size="small" text type="primary" @click="openEdit(s)">编辑</n-button>
          <n-popconfirm @positive-click="remove(s)">
            <template #trigger><n-button size="small" text type="error">删除</n-button></template>
            确定删除此科目?
          </n-popconfirm>
        </div>
      </template>
    </div>

    <n-modal v-model:show="show" preset="card" :title="editingId ? '编辑科目' : '新增科目'" style="max-width: 420px">
      <n-space vertical>
        <n-text>名称</n-text>
        <n-input v-model:value="form.name" data-testid="sub-name" placeholder="如:数学" />
        <n-text>领域/群别(选填)</n-text>
        <n-input v-model:value="form.domain" placeholder="如:数学领域" />
        <n-text>需要场地类型(选填)</n-text>
        <n-select v-model:value="form.required_room_type" :options="roomTypeOptions" clearable placeholder="不限" />
        <n-text>默认连堂长度</n-text>
        <n-input-number v-model:value="form.default_block_size" :min="1" :max="8" />
        <n-checkbox v-model:checked="form.is_major" data-testid="sub-is-major">
          主科(自动排课会尽量排在上午)
        </n-checkbox>
        <n-button type="primary" data-testid="sub-save" @click="save">储存</n-button>
      </n-space>
    </n-modal>
  </n-space>
</template>
