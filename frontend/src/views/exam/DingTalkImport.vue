<script setup lang="ts">
import {
  NAlert, NButton, NDataTable, NEmpty, NInput, NModal, NSelect,
  NSpace, NTag, NText, NTree, useMessage,
} from 'naive-ui'
import type { DataTableColumns, TreeOption } from 'naive-ui'
import { computed, h, onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import {
  getDingTalkDepartments, importDingTalkStudents, previewDingTalkStudents,
} from '@/api/exam'
import type {
  DingTalkDept, DingTalkPreview, DingTalkPreviewMember, ImportResult,
} from '@/api/exam'
import type { ClassUnit } from '@/api/basedata'

const props = defineProps<{
  semesterId: number
  classes: ClassUnit[]
}>()
const emit = defineEmits<{
  (e: 'done'): void
  (e: 'close'): void
}>()

const message = useMessage()
const visible = ref(true)

const classOptions = computed(() =>
  props.classes.map((c) => ({ label: `${c.grade} 年级 ${c.name}`, value: c.id })),
)

// ── 部门树 ──
const depts = ref<DingTalkDept[]>([])
const deptLoading = ref(false)
const deptError = ref('')
const treeData = ref<TreeOption[]>([])
const expandedKeys = ref<number[]>([])
const selectedKeys = ref<number[]>([])
const deptPathById = new Map<number, string[]>()

function toTreeOptions(nodes: DingTalkDept[], path: string[]): TreeOption[] {
  return nodes.map((n) => {
    const p = [...path, n.name]
    deptPathById.set(n.dept_id, p)
    return {
      label: n.name,
      key: n.dept_id,
      children: n.children?.length ? toTreeOptions(n.children, p) : undefined,
    }
  })
}

async function loadDepartments() {
  deptLoading.value = true
  deptError.value = ''
  try {
    depts.value = await getDingTalkDepartments()
    treeData.value = toTreeOptions(depts.value, [])
    expandedKeys.value = [...deptPathById.keys()]
  } catch (e) {
    deptError.value = (e as ApiError).detail || (e as Error).message || '钉钉部门加载失败'
  } finally {
    deptLoading.value = false
  }
}

onMounted(() => void loadDepartments())

// ── 预览 ──
const selectedDeptId = ref<number | null>(null)
const selectedDeptPath = ref<string[]>([])
const preview = ref<DingTalkPreview | null>(null)
const previewLoading = ref(false)
const previewError = ref('')
const targetClassId = ref<number | null>(null)
const checkedKeys = ref<string[]>([])
const editedNo = ref<Record<string, string>>({})
const importing = ref(false)
const importResult = ref<(ImportResult & { skipped_detail?: string[] }) | null>(null)

function studentNoOf(row: DingTalkPreviewMember): string {
  return (editedNo.value[row.userid] ?? row.student_no ?? '').trim()
}

function rowSelectable(row: DingTalkPreviewMember): boolean {
  if (row.exists === 'same_name') return false
  return !!studentNoOf(row)
}

function defaultChecked(rows: DingTalkPreviewMember[]): string[] {
  return rows.filter((r) => rowSelectable(r)).map((r) => r.userid)
}

async function loadPreview(explicitClassId?: number | null) {
  if (!selectedDeptId.value) return
  previewLoading.value = true
  previewError.value = ''
  importResult.value = null
  try {
    const data = await previewDingTalkStudents({
      semester_id: props.semesterId,
      dept_id: selectedDeptId.value,
      dept_path: selectedDeptPath.value,
      class_unit_id: explicitClassId ?? undefined,
    })
    preview.value = data
    if (explicitClassId === undefined) {
      targetClassId.value = data.suggested_class_unit_id
    }
    checkedKeys.value = defaultChecked(data.students)
  } catch (e) {
    previewError.value = (e as ApiError).detail || (e as Error).message || '预览加载失败'
  } finally {
    previewLoading.value = false
  }
}

function onSelectDept(keys: number[]) {
  selectedKeys.value = keys
  if (!keys.length) return
  selectedDeptId.value = keys[0]
  selectedDeptPath.value = deptPathById.get(keys[0]) ?? []
  editedNo.value = {}
  void loadPreview()
}

function onClassChange(v: number | null) {
  targetClassId.value = v
  void loadPreview(v)
}

function onNoInput(row: DingTalkPreviewMember, v: string) {
  editedNo.value = { ...editedNo.value, [row.userid]: v }
  const key = row.userid
  if (v.trim()) {
    if (!checkedKeys.value.includes(key)) checkedKeys.value = [...checkedKeys.value, key]
  } else {
    checkedKeys.value = checkedKeys.value.filter((k) => k !== key)
  }
}

const columns = computed<DataTableColumns<DingTalkPreviewMember>>(() => [
  {
    type: 'selection',
    width: 40,
    disabled: (row) => !rowSelectable(row),
  },
  { title: '姓名', key: 'name', width: 100 },
  {
    title: '学号',
    key: 'student_no',
    width: 150,
    render: (row) => row.student_no
      ? h('span', row.student_no)
      : h(NInput, {
        size: 'small',
        placeholder: '待补,填学号',
        value: editedNo.value[row.userid] ?? '',
        style: 'width: 130px',
        'onUpdate:value': (v: string) => onNoInput(row, v),
      }),
  },
  {
    title: '手机号(仅核对)',
    key: 'mobile',
    width: 130,
    render: (row) => row.mobile ?? '—',
  },
  {
    title: '状态',
    key: 'exists',
    width: 110,
    render: (row) => row.exists === 'new'
      ? h(NTag, { type: 'success', size: 'small' }, () => '新增')
      : row.exists === 'update'
        ? h(NTag, { type: 'warning', size: 'small' }, () => '按学号更新')
        : h(NTag, { size: 'small' }, () => '同名已存在'),
  },
  {
    title: '缺失',
    key: 'missing',
    render: (row) => row.missing_fields.length ? row.missing_fields.join('、') : '—',
  },
])

const checkedRows = computed(() =>
  (preview.value?.students ?? []).filter((r) => checkedKeys.value.includes(r.userid)),
)

async function onConfirm() {
  if (!preview.value || !targetClassId.value || !selectedDeptId.value) return
  if (!checkedRows.value.length) { message.warning('请先勾选要导入的学生'); return }
  importing.value = true
  try {
    const res = await importDingTalkStudents({
      semester_id: props.semesterId,
      dept_id: selectedDeptId.value,
      class_unit_id: targetClassId.value,
      students: checkedRows.value.map((r) => ({
        userid: r.userid, name: r.name, student_no: studentNoOf(r),
      })),
    })
    importResult.value = res
    if (!res.errors.length) {
      message.success(`导入完成:新增 ${res.created} 人,更新 ${res.updated} 人,跳过 ${res.skipped ?? 0} 人`)
    }
  } catch (e) {
    message.error((e as ApiError).detail || (e as Error).message || '导入失败')
  } finally {
    importing.value = false
  }
}

function onClose() {
  visible.value = false
  emit('close')
}
</script>

<template>
  <n-modal
    v-model:show="visible" preset="card" title="从钉钉导入学生"
    style="max-width: 880px" :mask-closable="false" @update:show="(v) => { if (!v) onClose() }"
  >
    <!-- 导入结果:成功后显示,点完成回列表 -->
    <template v-if="importResult && !importResult.errors.length">
      <n-space vertical>
        <n-text>
          新增 {{ importResult.created }} 人,更新 {{ importResult.updated }} 人,
          跳过 {{ importResult.skipped ?? 0 }} 人。
        </n-text>
        <n-alert v-if="importResult.skipped_detail?.length" type="info" title="跳过明细">
          <div v-for="(d, i) in importResult.skipped_detail" :key="i" style="font-size: 13px">{{ d }}</div>
        </n-alert>
        <n-text type="success">全部导入成功,无错误行。</n-text>
        <n-button type="primary" @click="emit('done')">完成</n-button>
      </n-space>
    </template>

    <template v-else>
      <!-- 第一步:选钉钉部门 -->
      <n-alert v-if="deptError" type="error" style="margin-bottom: 12px">{{ deptError }}</n-alert>
      <n-text depth="3" style="font-size: 13px">
        先选钉钉里的班级部门,再预览成员、勾选导入。只认家校通讯录的身份:学生才能导,
        家长与老师会自动过滤。
      </n-text>
      <n-tree
        v-model:selected-keys="selectedKeys" :data="treeData" :loading="deptLoading"
        :default-expanded-keys="expandedKeys"
        block-line style="margin-top: 12px; max-height: 260px; overflow: auto"
        @update:selected-keys="onSelectDept"
      />
      <n-empty v-if="!deptLoading && !treeData.length && !deptError" description="钉钉里没有部门" />

      <!-- 第二步:预览 -->
      <template v-if="preview">
        <n-alert v-if="previewError" type="error" style="margin-top: 12px">{{ previewError }}</n-alert>
        <div style="margin-top: 16px">
          <div class="ios-section-title">预览:{{ preview.dept_path.join(' > ') }}</div>
          <n-alert type="info" style="margin-bottom: 12px">
            本部门钉钉成员 {{ preview.total_members }} 人:学生 {{ preview.student_count }} 人、
            家长 {{ preview.guardian_count }} 人、老师 {{ preview.teacher_count }} 人已自动过滤,
            不可导入;身份未确认 {{ preview.unknown_count }} 人,需用 Excel 或手工处理。
          </n-alert>
          <n-space align="center" style="margin-bottom: 12px">
            <n-text>导入到班级</n-text>
            <n-select
              :value="targetClassId" :options="classOptions" placeholder="选择班级"
              style="width: 220px" @update:value="onClassChange"
            />
            <n-text v-if="preview.suggested_class_name" depth="3" style="font-size: 12px">
              已按部门名匹配“{{ preview.suggested_class_name }}”,不对可改。
            </n-text>
          </n-space>
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            手机号仅供核对,不会写入学生档案;不设家长电话。
            性别钉钉不提供,导入后为空,以后在档案里补。学号标“待补”的行须填好学号才能勾选。
          </n-text>
          <n-data-table
            v-model:checked-row-keys="checkedKeys" :columns="columns" :data="preview.students"
            :row-key="(row: DingTalkPreviewMember) => row.userid" :loading="previewLoading"
            :bordered="false" :single-line="false" :max-height="320"
          />
          <n-empty v-if="!previewLoading && !preview.students.length" description="该部门下没有学生" />
          <div v-if="preview.unconfirmed.length" style="margin-top: 12px">
            <div class="ios-section-title">身份未确认(不可导入)</div>
            <div v-for="u in preview.unconfirmed" :key="u.userid" class="ios-row">
              <div class="ios-row-main">
                <span class="ios-row-title">{{ u.name }}</span>
                <span class="ios-row-sub" style="margin-left: 8px">
                  {{ u.mobile ?? '无手机号' }} · {{ u.reason }}
                </span>
              </div>
            </div>
          </div>
          <n-alert v-if="importResult && importResult.errors.length" type="warning" title="以下行导入失败,未入库" style="margin-top: 12px">
            <div v-for="(err, i) in importResult.errors" :key="i" style="font-size: 13px">{{ err }}</div>
          </n-alert>
          <n-space style="margin-top: 16px">
            <n-button
              type="primary" :loading="importing" :disabled="!targetClassId || !checkedKeys.length"
              @click="onConfirm"
            >
              确认导入({{ checkedKeys.length }} 人)
            </n-button>
            <n-button @click="onClose">取消</n-button>
          </n-space>
        </div>
      </template>
      <n-text v-else-if="previewLoading" depth="3" style="font-size: 13px; display: block; margin-top: 12px">
        正在拉取钉钉成员并核对身份…
      </n-text>
    </template>
  </n-modal>
</template>
