<script setup lang="ts">
import {
  NAlert, NButton, NCheckbox, NList, NListItem, NRadioButton, NRadioGroup, NSpace, NText, NUpload,
  useMessage,
} from 'naive-ui'
import type { UploadFileInfo } from 'naive-ui'
import { computed, ref } from 'vue'
import { ENTITY_LABELS, downloadTemplate, uploadImport } from '@/api/imports'
import type { ImportEntity, ImportResult } from '@/api/imports'

const props = defineProps<{ semesterId: number }>()
const emit = defineEmits<{ imported: [] }>()
const message = useMessage()

const entity = ref<ImportEntity>('subjects')
// 默认勾选:导入教师时自动建号,老师不用单独申请帐号
const createAccounts = ref(true)
// 既有教师改为更新而非报错:每学年职务异动要改几十位老师(用户回报 #18)
const updateExisting = ref(false)
const selectedFile = ref<File | null>(null)
const uploading = ref(false)
const result = ref<ImportResult | null>(null)

const isTeacher = computed(() => entity.value === 'teachers')

async function onDownload() {
  try {
    await downloadTemplate(entity.value)
  } catch {
    message.error('范本下载失败')
  }
}

function onFileChange(data: { fileList: UploadFileInfo[] }) {
  selectedFile.value = data.fileList[0]?.file ?? null
  result.value = null
}

async function onUpload() {
  if (!selectedFile.value) {
    message.warning('请先选择档案')
    return
  }
  uploading.value = true
  result.value = null
  try {
    const r = await uploadImport(
      entity.value, props.semesterId, selectedFile.value,
      isTeacher.value && createAccounts.value,
      isTeacher.value && updateExisting.value,
    )
    result.value = r
    if (r.errors.length === 0) {
      message.success(r.updated
        ? `成功新增 ${r.imported} 笔、更新 ${r.updated} 笔`
        : `成功导入 ${r.imported} 笔`)
      emit('imported')
    } else {
      message.error('导入未完成,请修正错误后重试')
    }
  } catch (e) {
    message.error((e as Error).message || '导入失败')
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <n-space vertical size="large" style="max-width: 640px">
    <n-alert type="info" :show-icon="true">
      导入步骤:① 选择资料类型 → ② 下载范本并填写(第 4 列起填,说明/范例列会自动略过)→ ③ 上传。
      任一列有误将全部不导入,并列出错误列号。
    </n-alert>

    <n-space vertical>
      <n-text strong>① 资料类型</n-text>
      <n-radio-group v-model:value="entity">
        <n-radio-button v-for="(label, key) in ENTITY_LABELS" :key="key" :value="key">
          {{ label }}
        </n-radio-button>
      </n-radio-group>
    </n-space>

    <n-space vertical>
      <n-text strong>② 下载范本</n-text>
      <n-button @click="onDownload">下载「{{ ENTITY_LABELS[entity] }}」范本</n-button>
    </n-space>

    <n-space vertical>
      <n-text strong>③ 上传填好的档案</n-text>
      <n-checkbox v-if="isTeacher" v-model:checked="createAccounts">
        自动为每位教师建立登录帐号(帐号=姓名,初始密码 admin,首次登录强制改密码;重名自动加数字后缀)
      </n-checkbox>
      <n-text v-if="isTeacher && createAccounts" depth="3" style="font-size: 13px">
        Excel 里「登录帐号」那列留空就自动用姓名,填了就用填的值;老师拿到帐号就能自己登录,不用单独申请。
      </n-text>
      <n-checkbox v-if="isTeacher" v-model:checked="updateExisting" data-testid="import-update">
        既有教师改为更新资料(以姓名＋身分末四码比对)
      </n-checkbox>
      <n-text v-if="isTeacher && updateExisting" depth="3" style="font-size: 13px">
        只覆盖有填的栏位,空白保留原值;行政职称填「无」代表卸任,数字栏要归零请填 0。
        既有教师若尚未绑定帐号,勾选建立帐号时也会自动补建(帐号=姓名)。
      </n-text>
      <n-upload :max="1" :default-upload="false" accept=".xlsx" @change="onFileChange">
        <n-button>选择档案</n-button>
      </n-upload>
      <n-button type="primary" :loading="uploading" :disabled="!selectedFile" @click="onUpload">
        开始导入
      </n-button>
    </n-space>

    <n-alert v-if="result && result.errors.length === 0" type="success" data-testid="import-ok">
      <template v-if="result.updated">
        新增 {{ result.imported }} 笔、更新 {{ result.updated }} 笔。
      </template>
      <template v-else>成功导入 {{ result.imported }} 笔资料。</template>
    </n-alert>
    <n-alert v-if="result && result.errors.length > 0" type="error" title="导入失败(资料库未写入)">
      <n-list>
        <n-list-item v-for="(err, i) in result.errors" :key="i">
          <n-text>{{ err }}</n-text>
        </n-list-item>
      </n-list>
    </n-alert>
  </n-space>
</template>
