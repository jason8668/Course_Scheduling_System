<script setup lang="ts">
import {
  NButton, NEmpty, NInput, NInputNumber, NModal, NPopconfirm, NSelect, NSpace, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import {
  ROOM_TYPE_LABELS, createRoom, deleteRoom, listRooms, listSubjects, updateRoom,
} from '@/api/basedata'
import type { Room, RoomType, Subject } from '@/api/basedata'

const props = defineProps<{ semesterId: number }>()
const message = useMessage()

const items = ref<Room[]>([])
const subjects = ref<Subject[]>([])
const search = ref('')

const roomTypeOptions = (Object.keys(ROOM_TYPE_LABELS) as RoomType[]).map((t) => ({
  label: ROOM_TYPE_LABELS[t], value: t,
}))
const subjectOptions = computed(() => subjects.value.map((s) => ({ label: s.name, value: s.id })))

async function reload() {
  items.value = await listRooms(props.semesterId, search.value || undefined)
}
onMounted(async () => {
  subjects.value = await listSubjects(props.semesterId)
  await reload()
})

const show = ref(false)
const editingId = ref<number | null>(null)
const form = ref<{ name: string; room_type: RoomType; capacity: number | null; subject_ids: number[] }>({
  name: '', room_type: 'normal', capacity: null, subject_ids: [],
})

function openCreate() {
  editingId.value = null
  form.value = { name: '', room_type: 'normal', capacity: null, subject_ids: [] }
  show.value = true
}
function openEdit(r: Room) {
  editingId.value = r.id
  form.value = {
    name: r.name, room_type: r.room_type, capacity: r.capacity,
    subject_ids: r.subjects.map((s) => s.id),
  }
  show.value = true
}

async function save() {
  if (!form.value.name) {
    message.warning('请输入场地名称')
    return
  }
  try {
    if (editingId.value) await updateRoom(editingId.value, form.value)
    else await createRoom(props.semesterId, form.value)
    show.value = false
    message.success('已储存')
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '储存失败')
  }
}

async function remove(r: Room) {
  try {
    await deleteRoom(r.id)
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
      <n-input v-model:value="search" placeholder="搜索场地名称" clearable style="width: 200px" @input="reload" />
      <n-button type="primary" round @click="openCreate">新增场地</n-button>
    </n-space>

    <div class="ios-card">
      <n-empty v-if="items.length === 0" description="尚无场地" style="padding: 24px 0" />
      <template v-else>
        <div v-for="r in items" :key="r.id" class="ios-row">
          <div class="ios-row-main">
            <span class="ios-row-title">{{ r.name }}</span>
            <span class="ios-row-sub" style="margin-left: 8px">
              {{ ROOM_TYPE_LABELS[r.room_type] }} · 容量 {{ r.capacity ?? '—' }}
              · {{ r.subjects.map((s) => s.name).join('、') || '适用科目不限' }}
            </span>
          </div>
          <n-button size="small" text type="primary" @click="openEdit(r)">编辑</n-button>
          <n-popconfirm @positive-click="remove(r)">
            <template #trigger><n-button size="small" text type="error">删除</n-button></template>
            确定删除此场地?
          </n-popconfirm>
        </div>
      </template>
    </div>

    <n-modal v-model:show="show" preset="card" :title="editingId ? '编辑场地' : '新增场地'" style="max-width: 440px">
      <n-space vertical>
        <n-text>名称</n-text>
        <n-input v-model:value="form.name" placeholder="如:机械实习工场" />
        <n-text>类型</n-text>
        <n-select v-model:value="form.room_type" :options="roomTypeOptions" />
        <n-text>容量(选填)</n-text>
        <n-input-number v-model:value="form.capacity" :min="0" />
        <n-text>适用科目(选填)</n-text>
        <n-select v-model:value="form.subject_ids" multiple :options="subjectOptions" placeholder="可多选" />
        <n-button type="primary" @click="save">储存</n-button>
      </n-space>
    </n-modal>
  </n-space>
</template>
