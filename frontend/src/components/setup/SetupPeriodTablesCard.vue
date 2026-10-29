<script setup lang="ts">
import {
  NButton, NEmpty, NInput, NPopconfirm, NSelect, NSpace, NText, useMessage,
} from 'naive-ui'
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import {
  createPeriodTable, deletePeriodTable, getSemester, updatePeriodTable,
} from '@/api/semesters'
import type { PeriodTable } from '@/api/semesters'

const props = defineProps<{ semesterId: number | null }>()
const message = useMessage()
const router = useRouter()

const tables = ref<PeriodTable[]>([])
async function reload() {
  if (!props.semesterId) {
    tables.value = []
    return
  }
  const sem = await getSemester(props.semesterId)
  tables.value = sem.period_tables
}
watch(() => props.semesterId, reload)
onMounted(reload)

const name = ref('')
const weekdays = ref(5)
async function onCreate() {
  if (!props.semesterId) return
  if (!name.value) return message.warning('请输入节次表名称')
  try {
    await createPeriodTable(props.semesterId, {
      name: name.value, num_weekdays: weekdays.value,
      is_default: tables.value.length === 0,
    })
    name.value = ''
    message.success('已建立节次表')
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '建立失败')
  }
}
async function onSetDefault(t: PeriodTable) {
  await updatePeriodTable(t.id, { is_default: true })
  message.success(`已设「${t.name}」为默认`)
  await reload()
}
async function onDelete(t: PeriodTable) {
  await deletePeriodTable(t.id)
  message.success('已删除节次表')
  await reload()
}
function openEditor(t: PeriodTable) {
  void router.push({ name: 'period-table-editor', params: { id: t.id } })
}
</script>

<template>
  <div>
    <n-empty v-if="!semesterId" description="请先在上面建立或选择学期" style="padding: 12px 0" />
    <template v-else>
      <n-space vertical size="small">
        <n-space v-for="t in tables" :key="t.id" align="center" :wrap="true">
          <n-text strong style="font-size: 14px">
            {{ t.name }}
          </n-text>
          <span v-if="t.is_default" class="ios-chip">默认</span>
          <n-text depth="3" style="font-size: 13px">
            每周 {{ t.num_weekdays }} 天 · {{ t.periods.length }} 个时段
          </n-text>
          <n-button size="small" text type="primary" @click="openEditor(t)">
            编辑时段
          </n-button>
          <n-button v-if="!t.is_default" size="small" text @click="onSetDefault(t)">
            设为默认
          </n-button>
          <n-popconfirm @positive-click="onDelete(t)">
            <template #trigger>
              <n-button size="small" text type="error">
                删除
              </n-button>
            </template>
            确定删除这张节次表？
          </n-popconfirm>
        </n-space>
        <n-empty v-if="!tables.length" description="还没有节次表，先建一张" />
      </n-space>
      <n-space align="center" :wrap="true" style="margin-top: 12px">
        <n-input v-model:value="name" placeholder="节次表名称，如 默认" style="width: 200px" />
        <n-select
          v-model:value="weekdays" :options="[5, 6, 7].map((d) => ({ label: `每周 ${d} 天`, value: d }))"
          style="width: 130px"
        />
        <n-text depth="3" style="font-size: 13px">
          时段格子（第几节、几点到几点、午休等）点「编辑时段」进去排
        </n-text>
        <n-button size="small" type="primary" round @click="onCreate">
          新建节次表
        </n-button>
      </n-space>
    </template>
  </div>
</template>
