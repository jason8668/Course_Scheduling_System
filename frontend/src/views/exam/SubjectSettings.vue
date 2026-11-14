<script setup lang="ts">
import {
  NAlert, NButton, NCheckbox, NEmpty, NInputNumber, NSelect, NSpace, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref, watch } from 'vue'
import type { ApiError } from '@/api/client'
import {
  DEFAULT_SUBJECT_SETTING, listSubjectSettings, saveSubjectSettings,
} from '@/api/exam'
import type { SubjectSetting } from '@/api/exam'
import { listSemesters } from '@/api/semesters'
import type { SemesterListItem } from '@/api/semesters'
import { useAuthStore } from '@/stores/auth'

const message = useMessage()
const auth = useAuthStore()
// 学科分值写权限(后端逐科校验):admin/director 可改全部,教研组长只改本科目,
// 其他教师只读。前端无法得知教研组长的本科目清单,保存时后端对无权科目回 403,
// 前端原样展示后端提示,不假装有权限。
const canEdit = computed(() =>
  auth.hasRole('admin') || auth.hasRole('director') || auth.hasRole('scheduler'))

const semesters = ref<SemesterListItem[]>([])
const semesterId = ref<number | null>(null)
const semesterOptions = computed(() =>
  semesters.value.map((s) => ({ label: s.label, value: s.id })),
)
const items = ref<SubjectSetting[]>([])
const loading = ref(false)
const forbidden = ref(false)
const dirty = ref(false)

async function reload() {
  if (!semesterId.value) return
  loading.value = true
  forbidden.value = false
  try {
    const res = await listSubjectSettings(semesterId.value)
    items.value = res.items
    dirty.value = false
  } catch (e) {
    if ((e as ApiError).status === 403) forbidden.value = true
    else message.error((e as ApiError).detail || '加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try {
    semesters.value = await listSemesters()
    if (semesters.value.length) semesterId.value = semesters.value[0].id
  } catch (e) {
    message.error((e as ApiError).detail || '学期加载失败')
  }
})
watch(semesterId, (v, old) => {
  if (v && v !== old) void reload()
})

async function saveAll() {
  if (!semesterId.value) return
  // 后端校验:及格线/优秀线不可高于满分,及格线不可高于优秀线;先在前端拦一次。
  for (const s of items.value) {
    if (s.pass_line > s.full_score) { message.warning(`${s.subject_name}:及格线不可高于满分`); return }
    if (s.excellent_line > s.full_score) { message.warning(`${s.subject_name}:优秀线不可高于满分`); return }
    if (s.pass_line > s.excellent_line) { message.warning(`${s.subject_name}:及格线不可高于优秀线`); return }
  }
  try {
    const res = await saveSubjectSettings(semesterId.value, items.value)
    items.value = res.items
    dirty.value = false
    message.success('学科分值已批量保存')
  } catch (e) {
    message.error((e as ApiError).detail || '保存失败')
  }
}
</script>

<template>
  <div class="ios-page">
    <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap">
      <h1 class="ios-title">学科分值</h1>
      <n-select
        v-model:value="semesterId"
        :options="semesterOptions"
        placeholder="选择学期"
        style="width: 240px"
      />
    </div>

    <n-alert v-if="!semesterId" type="info" style="margin-top: 16px">
      请先建立学期,再回此页设置学科分值。
    </n-alert>
    <n-alert v-else-if="forbidden" type="error" style="margin-top: 16px">
      无权查看学科分值设置。
    </n-alert>

    <template v-else>
      <div class="ios-card" style="margin-top: 16px">
        <div class="ios-card-body">
          <n-text depth="3" style="font-size: 13px">
            未设置的科目显示默认值:满分 {{ DEFAULT_SUBJECT_SETTING.full_score }}、
            及格线 {{ DEFAULT_SUBJECT_SETTING.pass_line }}、
            优秀线 {{ DEFAULT_SUBJECT_SETTING.excellent_line }}、
            计入总分、折算比例 {{ DEFAULT_SUBJECT_SETTING.conversion_ratio }}。
            哪些科目计入总分、是否含体育/实验/综合素质,待学校确认总分构成口径后以此为准。
          </n-text>
          <n-alert v-if="!canEdit" type="info" style="margin-top: 12px">
            你目前只有查看权限:学科分值由教务修改,教研组长只改本科目。
          </n-alert>
          <n-empty v-if="!loading && items.length === 0" description="本学期尚无科目,请先在开学建置里建立科目" />
          <div v-for="s in items" :key="s.subject_id" class="ios-row" style="align-items: center">
            <div class="ios-row-main" style="min-width: 90px">
              <span class="ios-row-title">{{ s.subject_name }}</span>
            </div>
            <n-space :wrap="true" align="center" size="small">
              <span style="font-size: 13px">满分</span>
              <n-input-number
                v-model:value="s.full_score" :min="1" :max="1000" :disabled="!canEdit"
                style="width: 90px" @update:value="dirty = true"
              />
              <span style="font-size: 13px">及格线</span>
              <n-input-number
                v-model:value="s.pass_line" :min="0" :max="1000" :disabled="!canEdit"
                style="width: 90px" @update:value="dirty = true"
              />
              <span style="font-size: 13px">优秀线</span>
              <n-input-number
                v-model:value="s.excellent_line" :min="0" :max="1000" :disabled="!canEdit"
                style="width: 90px" @update:value="dirty = true"
              />
              <span style="font-size: 13px">折算比例</span>
              <n-input-number
                v-model:value="s.conversion_ratio" :min="0.1" :max="10" :step="0.1"
                :disabled="!canEdit" style="width: 90px" @update:value="dirty = true"
              />
              <n-checkbox v-model:checked="s.counts_toward_total" :disabled="!canEdit" @update:checked="dirty = true">
                计入总分
              </n-checkbox>
            </n-space>
          </div>
          <n-space style="margin-top: 16px">
            <n-button v-if="canEdit" type="primary" :disabled="!dirty" @click="saveAll">
              批量保存
            </n-button>
            <n-text v-if="dirty" depth="3" style="font-size: 13px">有未保存的修改</n-text>
          </n-space>
        </div>
      </div>
    </template>
  </div>
</template>
