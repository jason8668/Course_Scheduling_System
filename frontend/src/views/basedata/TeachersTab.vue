<script setup lang="ts">
import {
  NButton, NDivider, NInput, NInputNumber, NModal, NPopconfirm, NSelect, NSpace, NSwitch, NTag, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import {
  createTeacher, createTeacherAccount, deleteTeacher, getTeacherAccount, getTeacherDeleteImpact,
  listBindableAccounts, listSubjects, listTeachers, resetTeacherPassword,
  setTeacherAccountActive, updateTeacher,
} from '@/api/basedata'
import type {
  BindableAccount, Subject, Teacher, TeacherAccount, TeacherDeleteImpact,
} from '@/api/basedata'
import TeacherTimeRules from './TeacherTimeRules.vue'

const props = defineProps<{ semesterId: number }>()
const message = useMessage()

const items = ref<Teacher[]>([])
const subjects = ref<Subject[]>([])
const accounts = ref<BindableAccount[]>([])
const search = ref('')
const subjectOptions = computed(() => subjects.value.map((s) => ({ label: s.name, value: s.id })))
const accountOptions = computed(() =>
  accounts.value.map((a) => ({ label: `${a.display_name}(${a.username})`, value: a.id })),
)

async function reload() {
  items.value = await listTeachers(props.semesterId, search.value || undefined)
}
onMounted(async () => {
  subjects.value = await listSubjects(props.semesterId)
  await reload()
})

const show = ref(false)
const editingId = ref<number | null>(null)
interface TeacherForm {
  name: string; base_periods: number; admin_title: string; admin_reduction: number
  is_external: boolean; is_active: boolean; subject_ids: number[]
  email: string; phone: string; line_id: string; user_id: number | null
}
function emptyForm(): TeacherForm {
  return {
    name: '', base_periods: 0, admin_title: '', admin_reduction: 0,
    is_external: false, is_active: true, subject_ids: [],
    email: '', phone: '', line_id: '', user_id: null,
  }
}
const form = ref<TeacherForm>(emptyForm())

// 事后补开登录帐号(导入时没勾、或后来才要用系统的老师);savedUserId 是「已存档」的绑定,
// 下拉选单改了还没存不算,重设密码要以存档状态为准
const savedUserId = ref<number | null>(null)
const newUsername = ref('')
const newPassword = ref('')
const accountBusy = ref(false)
// 停用的帐号不会出现在「可绑定帐号」清单里,所以编辑时直接问这位教师的帐号
const boundAccount = ref<TeacherAccount | null>(null)

async function loadBoundAccount(teacherId: number) {
  boundAccount.value = await getTeacherAccount(teacherId)
  savedUserId.value = boundAccount.value?.id ?? null
}

async function onToggleAccountActive() {
  if (editingId.value === null || !boundAccount.value) return
  const next = !boundAccount.value.is_active
  accountBusy.value = true
  try {
    boundAccount.value = await setTeacherAccountActive(editingId.value, next)
    message.success(next
      ? '已启用帐号,这位老师可以再登录了'
      : '已停用帐号,这位老师无法再登录;资料与纪录都保留')
  } catch (e) {
    message.error((e as ApiError).detail || '变更帐号状态失败')
  } finally {
    accountBusy.value = false
  }
}

async function onCreateAccount() {
  const username = newUsername.value.trim()
  if (!username || editingId.value === null) {
    message.warning('请输入登录帐号')
    return
  }
  accountBusy.value = true
  try {
    const acc = await createTeacherAccount(editingId.value, username, newPassword.value || undefined)
    boundAccount.value = acc
    savedUserId.value = acc.id
    form.value.user_id = acc.id
    newUsername.value = ''
    message.success(newPassword.value
      ? `已建立帐号 ${acc.username},密码为你刚才输入的值;老师首次登录须自行修改`
      : `已建立帐号 ${acc.username},使用系统默认密码;老师首次登录须自行修改`)
    newPassword.value = ''
  } catch (e) {
    message.error((e as ApiError).detail || '建立帐号失败')
    return
  } finally {
    // 只在送出期间锁住按钮;下面的清单重载是背景工作,不该让「停用帐号」按钮一直是停用状态
    accountBusy.value = false
  }
  await loadAccounts(editingId.value)
  await reload()
}

async function onResetPassword() {
  if (editingId.value === null) return
  accountBusy.value = true
  try {
    await resetTeacherPassword(editingId.value, newPassword.value || undefined)
    message.success(newPassword.value
      ? '密码已重设为你刚才输入的值;老师下次登录须自行修改'
      : '密码已重设为系统默认密码;老师下次登录须自行修改')
    newPassword.value = ''
  } catch (e) {
    message.error((e as ApiError).detail || '重设密码失败')
  } finally {
    accountBusy.value = false
  }
}

async function loadAccounts(currentTeacherId?: number) {
  accounts.value = await listBindableAccounts(props.semesterId, currentTeacherId)
}

async function openCreate() {
  editingId.value = null
  form.value = emptyForm()
  boundAccount.value = null
  savedUserId.value = null
  newUsername.value = ''
  newPassword.value = ''
  await loadAccounts()
  show.value = true
}
async function openEdit(t: Teacher) {
  editingId.value = t.id
  form.value = {
    name: t.name, base_periods: t.base_periods, admin_title: t.admin_title ?? '',
    admin_reduction: t.admin_reduction, is_external: t.is_external, is_active: t.is_active,
    subject_ids: t.subjects.map((s) => s.id),
    email: t.email ?? '', phone: t.phone ?? '', line_id: t.line_id ?? '', user_id: t.user_id,
  }
  savedUserId.value = t.user_id
  boundAccount.value = null
  newUsername.value = ''
  newPassword.value = ''
  await Promise.all([loadAccounts(t.id), t.user_id ? loadBoundAccount(t.id) : Promise.resolve()])
  show.value = true
}

async function save() {
  if (!form.value.name) {
    message.warning('请输入教师姓名')
    return
  }
  const body = {
    ...form.value,
    admin_title: form.value.admin_title || null,
    email: form.value.email || null,
    phone: form.value.phone || null,
    line_id: form.value.line_id || null,
  }
  try {
    if (editingId.value) await updateTeacher(editingId.value, body)
    else await createTeacher(props.semesterId, body)
    show.value = false
    message.success('已储存')
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '储存失败')
  }
}

// 删除教师会连带删掉请假纪录、配课关联,代课纪录也查不出是谁代的——先把后果讲清楚(#19)
const impact = ref<TeacherDeleteImpact | null>(null)
const impactFor = ref<number | null>(null)

async function loadImpact(t: Teacher) {
  impactFor.value = t.id
  impact.value = null
  try {
    impact.value = await getTeacherDeleteImpact(t.id)
  } catch {
    impact.value = null  // 查不到就只显示一般提醒,不挡住删除
  }
}

function impactText(t: Teacher): string {
  if (impactFor.value !== t.id || !impact.value) return ''
  const i = impact.value
  const parts: string[] = []
  if (i.leave_requests) parts.push(`${i.leave_requests} 张请假单`)
  if (i.substitutions) parts.push(`${i.substitutions} 笔调代课纪录`)
  if (i.assignments) parts.push(`${i.assignments} 笔配课的任课教师`)
  return parts.length ? parts.join('、') : ''
}

async function remove(t: Teacher) {
  try {
    await deleteTeacher(t.id)
    message.success('已删除')
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '删除失败')
  }
}

// 时段规则
const rulesShow = ref(false)
const rulesTeacher = ref<Teacher | null>(null)
function openRules(t: Teacher) {
  rulesTeacher.value = t
  rulesShow.value = true
}
</script>

<template>
  <n-space vertical>
    <n-space>
      <n-input v-model:value="search" placeholder="搜寻教师姓名" clearable style="width: 200px" @input="reload" />
      <n-button type="primary" data-testid="teacher-add" @click="openCreate">新增教师</n-button>
    </n-space>

    <table class="data-table">
      <thead>
        <tr><th>姓名</th><th>任教科目</th><th>基本课时</th><th>行政</th><th>帐号</th><th>状态</th><th>操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="t in items" :key="t.id">
          <td>
            {{ t.name }}
            <n-tag v-if="t.is_external" size="tiny" type="warning" style="margin-left: 4px">外聘</n-tag>
          </td>
          <td>
            <n-space size="small">
              <n-tag v-for="s in t.subjects" :key="s.id" size="small">{{ s.name }}</n-tag>
              <n-text v-if="t.subjects.length === 0" depth="3">—</n-text>
            </n-space>
          </td>
          <td>{{ t.base_periods }}</td>
          <td>{{ t.admin_title ? `${t.admin_title}(减 ${t.admin_reduction})` : '—' }}</td>
          <td>
            <n-tag v-if="t.user_id" size="small" type="info">已绑定</n-tag>
            <n-text v-else depth="3">—</n-text>
          </td>
          <td>
            <n-tag :type="t.is_active ? 'success' : 'default'" size="small">
              {{ t.is_active ? '在职' : '离职' }}
            </n-tag>
          </td>
          <td>
            <n-space>
              <n-button size="tiny" data-testid="teacher-edit" @click="openEdit(t)">编辑</n-button>
              <n-button size="tiny" @click="openRules(t)">时段规则</n-button>
              <n-popconfirm @positive-click="remove(t)">
                <template #trigger>
                  <n-button
                    size="tiny" type="error" ghost data-testid="teacher-delete"
                    @click="loadImpact(t)"
                  >
                    删除
                  </n-button>
                </template>
                <div style="max-width: 320px" data-testid="teacher-delete-confirm">
                  <div>确定删除教师「{{ t.name }}」?</div>
                  <div v-if="impactText(t)" style="margin-top: 6px">
                    将一并删除:<b>{{ impactText(t) }}</b>,之后查不回来。
                  </div>
                  <div v-if="t.user_id" style="margin-top: 6px">
                    其登录帐号会一并<b>停用</b>(帐号保留,但无法再登录)。
                  </div>
                  <div style="margin-top: 6px">
                    老师离职请改用:编辑里取消「在职」,并在帐号区块按「停用帐号」——历史纪录会完整保留。
                  </div>
                </div>
              </n-popconfirm>
            </n-space>
          </td>
        </tr>
        <tr v-if="items.length === 0"><td colspan="7"><n-text depth="3">尚无教师</n-text></td></tr>
      </tbody>
    </table>

    <n-modal v-model:show="show" preset="card" :title="editingId ? '编辑教师' : '新增教师'" style="max-width: 460px">
      <n-space vertical>
        <n-text>姓名</n-text>
        <n-input v-model:value="form.name" data-testid="teacher-name" placeholder="如:王小明" />
        <n-text>任教科目</n-text>
        <n-select v-model:value="form.subject_ids" multiple :options="subjectOptions" placeholder="可多选" />
        <n-space>
          <n-space vertical style="flex: 1">
            <n-text>基本课时</n-text>
            <n-input-number v-model:value="form.base_periods" :min="0" />
          </n-space>
          <n-space vertical style="flex: 1">
            <n-text>行政减课</n-text>
            <n-input-number v-model:value="form.admin_reduction" :min="0" />
          </n-space>
        </n-space>
        <n-text>行政职称(选填)</n-text>
        <n-input v-model:value="form.admin_title" placeholder="如:教学组长" />
        <n-space align="center">
          <n-text>外聘/业界师资</n-text>
          <n-switch v-model:value="form.is_external" />
          <n-text style="margin-left: 16px">在职</n-text>
          <n-switch v-model:value="form.is_active" />
        </n-space>

        <n-divider style="margin: 4px 0" title-placement="left">
          <n-text depth="3" style="font-size: 12px">联络信息(选填,供调代课通知)</n-text>
        </n-divider>
        <n-space>
          <n-space vertical style="flex: 1">
            <n-text>Email</n-text>
            <n-input v-model:value="form.email" data-testid="teacher-email" placeholder="通知寄送用" />
          </n-space>
          <n-space vertical style="flex: 1">
            <n-text>手机</n-text>
            <n-input v-model:value="form.phone" placeholder="人工联络用" />
          </n-space>
        </n-space>
        <n-text>LINE ID(选填,人工联络用)</n-text>
        <n-input v-model:value="form.line_id" placeholder="LINE ID" />
        <n-text>绑定登录帐号(选填)</n-text>
        <n-select
          v-model:value="form.user_id"
          data-testid="teacher-account"
          :options="accountOptions"
          clearable
          placeholder="绑定后此教师可用该帐号登录查课表/请假"
        />

        <!-- 导入时没建帐号的老师,在这里直接补一个;已经有帐号的则可重设密码 -->
        <template v-if="editingId !== null">
          <n-divider style="margin: 4px 0" />
          <template v-if="boundAccount">
            <n-space align="center">
              <n-text>登录帐号:<b>{{ boundAccount.username }}</b></n-text>
              <n-tag
                size="small" :type="boundAccount.is_active ? 'success' : 'warning'"
                data-testid="teacher-account-state"
              >
                {{ boundAccount.is_active ? '可登录' : '已停用' }}
              </n-tag>
              <n-button
                size="tiny" :loading="accountBusy"
                data-testid="teacher-account-toggle" @click="onToggleAccountActive"
              >
                {{ boundAccount.is_active ? '停用帐号' : '启用帐号' }}
              </n-button>
            </n-space>
            <n-text v-if="!boundAccount.is_active" depth="3" style="font-size: 13px">
              停用中:这位老师无法登录,但请假、调代课等历史纪录都保留。离职教师建议用这个方式,不要删除。
            </n-text>
            <n-space align="center">
              <n-input
                key="reset-password"
                v-model:value="newPassword" type="password" show-password-on="click"
                placeholder="新密码(留空=系统默认密码)" style="width: 230px"
                data-testid="teacher-reset-password"
              />
              <n-popconfirm @positive-click="onResetPassword">
                <template #trigger>
                  <n-button size="small" :loading="accountBusy" data-testid="teacher-reset-submit">
                    重设密码
                  </n-button>
                </template>
                重设后这位老师目前的登录状态会失效,下次登录必须自行改密码。确定重设?
              </n-popconfirm>
            </n-space>
          </template>
          <template v-else>
            <n-text depth="3">没有帐号?直接建立一个(自动绑定这位老师,首次登录须改密码)</n-text>
            <n-space align="center">
              <n-input
                key="new-username"
                v-model:value="newUsername" placeholder="登录帐号" style="width: 160px"
                data-testid="teacher-new-username"
              />
              <n-input
                key="new-password"
                v-model:value="newPassword" type="password" show-password-on="click"
                placeholder="默认密码(留空=系统默认)" style="width: 210px"
                data-testid="teacher-new-password"
              />
              <n-button
                size="small" :loading="accountBusy"
                data-testid="teacher-create-account" @click="onCreateAccount"
              >
                建立帐号
              </n-button>
            </n-space>
          </template>
        </template>

        <n-button type="primary" data-testid="teacher-save" @click="save">储存</n-button>
      </n-space>
    </n-modal>

    <n-modal
      v-model:show="rulesShow"
      preset="card"
      :title="`时段规则:${rulesTeacher?.name}`"
      style="max-width: 640px"
    >
      <TeacherTimeRules
        v-if="rulesTeacher"
        :teacher-id="rulesTeacher.id"
        :semester-id="semesterId"
        @saved="rulesShow = false"
      />
    </n-modal>
  </n-space>
</template>

<style scoped>
.data-table { border-collapse: collapse; width: 100%; }
.data-table th, .data-table td { border: 1px solid var(--n-border-color, #e0e0e0); padding: 8px 10px; text-align: left; }
.data-table th { background: rgba(128,128,128,0.08); font-weight: 600; }
</style>
