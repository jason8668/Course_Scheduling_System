<script setup lang="ts">
import {
  NButton, NInput, NInputNumber, NModal, NPopconfirm, NSelect, NSpace, NTag, NText, useMessage,
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
      <n-input v-model:value="search" placeholder="搜寻场地名称" clearable style="width: 200px" @input="reload" />
      <n-button type="primary" @click="openCreate">新增场地</n-button>
    </n-space>

    <table class="data-table">
      <thead>
        <tr><th>名称</th><th>类型</th><th>容量</th><th>适用科目</th><th>操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="r in items" :key="r.id">
          <td>{{ r.name }}</td>
          <td>{{ ROOM_TYPE_LABELS[r.room_type] }}</td>
          <td>{{ r.capacity ?? '—' }}</td>
          <td>
            <n-space size="small">
              <n-tag v-for="s in r.subjects" :key="s.id" size="small">{{ s.name }}</n-tag>
              <n-text v-if="r.subjects.length === 0" depth="3">—</n-text>
            </n-space>
          </td>
          <td>
            <n-space>
              <n-button size="tiny" @click="openEdit(r)">编辑</n-button>
              <n-popconfirm @positive-click="remove(r)">
                <template #trigger><n-button size="tiny" type="error" ghost>删除</n-button></template>
                确定删除此场地?
              </n-popconfirm>
            </n-space>
          </td>
        </tr>
        <tr v-if="items.length === 0"><td colspan="5"><n-text depth="3">尚无场地</n-text></td></tr>
      </tbody>
    </table>

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

<style scoped>
.data-table { border-collapse: collapse; width: 100%; }
.data-table th, .data-table td { border: 1px solid var(--n-border-color, #e0e0e0); padding: 8px 10px; text-align: left; }
.data-table th { background: rgba(128,128,128,0.08); font-weight: 600; }
</style>
