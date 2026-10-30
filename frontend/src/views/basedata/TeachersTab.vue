<script setup lang="ts">
import {
  NButton, NDivider, NEmpty, NInput, NInputNumber, NModal, NPopconfirm, NSelect, NSpace, NSwitch, NTag, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import {
  createTeacher, deleteTeacher, getTeacherAccount, getTeacherDeleteImpact,
  listSubjects, listTeachers, promoteTeacherGrades, resetTeacherPassword,
  updateTeacher,
} from '@/api/basedata'
import type {
  Subject, Teacher, TeacherAccount, TeacherDeleteImpact,
} from '@/api/basedata'
import { gradeLabel } from '@/api/substitutionLog'
import { useAuthStore } from '@/stores/auth'
import TeacherTimeRules from './TeacherTimeRules.vue'

const props = defineProps<{ semesterId: number }>()
const message = useMessage()
const auth = useAuthStore()

const items = ref<Teacher[]>([])
const subjects = ref<Subject[]>([])
const search = ref('')
const subjectOptions = computed(() => subjects.value.map((s) => ({ label: s.name, value: s.id })))
const gradeOptions = Array.from({ length: 12 }, (_, i) => ({
  label: gradeLabel(i + 1), value: i + 1,
}))

async function reload() {
  items.value = await listTeachers(props.semesterId, search.value || undefined)
}
// 全体升一年级确认框里各年级会动的人数(一人多年级时各计一次)
const promoteCounts = computed(() => {
  const counts: Record<number, number> = {}
  for (const t of items.value)
    for (const g of t.grade_ids ?? [])
      if (g === 7 || g === 8 || g === 9) counts[g] = (counts[g] ?? 0) + 1
  return counts
})
async function promoteAll() {
  try {
    const r = await promoteTeacherGrades(props.semesterId)
    message.success(`已升年级，${r.teachers_updated} 位教师的所属年级已调整`)
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '升年级失败')
  }
}
onMounted(async () => {
  subjects.value = await listSubjects(props.semesterId)
  await reload()
})

const show = ref(false)
const editingId = ref<number | null>(null)
interface TeacherForm {
  name: string; base_periods: number; admin_title: string; admin_reduction: number
  is_external: boolean; is_active: boolean; subject_ids: number[]; grade_ids: number[]
  is_grade_director: boolean
  email: string; phone: string; user_id: number | null
}
function emptyForm(): TeacherForm {
  return {
    name: '', base_periods: 0, admin_title: '', admin_reduction: 0,
    is_external: false, is_active: true, subject_ids: [], grade_ids: [],
    is_grade_director: false,
    email: '', phone: '', user_id: null,
  }
}
const form = ref<TeacherForm>(emptyForm())

// 手动侧(Jason 2026-10-30 定):手动建号已取消,手动绑定/停用/自设密码也不再提供;
// 这里只读显示已绑帐号,只有系统管理员能帮别人恢复默认密码,其他人连按钮都看不到。
const accountBusy = ref(false)
const boundAccount = ref<TeacherAccount | null>(null)

async function loadBoundAccount(teacherId: number) {
  boundAccount.value = await getTeacherAccount(teacherId)
}

async function onResetPassword() {
  if (editingId.value === null) return
  accountBusy.value = true
  try {
    await resetTeacherPassword(editingId.value)
    message.success('密码已恢复为系统默认密码;老师下次登录须自行修改')
  } catch (e) {
    message.error((e as ApiError).detail || '恢复默认密码失败')
  } finally {
    accountBusy.value = false
  }
}

async function openCreate() {
  editingId.value = null
  form.value = emptyForm()
  boundAccount.value = null
  show.value = true
}
async function openEdit(t: Teacher) {
  editingId.value = t.id
  form.value = {
    name: t.name, base_periods: t.base_periods, admin_title: t.admin_title ?? '',
    admin_reduction: t.admin_reduction, is_external: t.is_external, is_active: t.is_active,
    subject_ids: t.subjects.map((s) => s.id),
    grade_ids: t.grade_ids ?? [],
    is_grade_director: t.is_grade_director ?? false,
    email: t.email ?? '', phone: t.phone ?? '', user_id: t.user_id,
  }
  boundAccount.value = null
  if (t.user_id) await loadBoundAccount(t.id)
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
      <n-input v-model:value="search" placeholder="搜索教师姓名" clearable style="width: 200px" @input="reload" />
      <n-button type="primary" round data-testid="teacher-add" @click="openCreate">新增教师</n-button>
      <n-popconfirm @positive-click="promoteAll">
        <template #trigger>
          <n-button data-testid="teacher-promote">全体升一年级</n-button>
        </template>
        <div style="max-width: 340px">
          <div>把本学期全部教师的所属年级升一年：七年级→八年级，八年级→九年级，九年级→七年级（循环带新生）。</div>
          <div style="margin-top: 6px">
            七年级 {{ promoteCounts[7] ?? 0 }} 人、八年级 {{ promoteCounts[8] ?? 0 }} 人、
            九年级 {{ promoteCounts[9] ?? 0 }} 人会动；没填年级的不动，主任的年级范围会跟着变。
          </div>
        </div>
      </n-popconfirm>
    </n-space>

    <div class="ios-card">
      <n-empty v-if="items.length === 0" description="尚无教师" style="padding: 24px 0" />
      <template v-else>
        <div v-for="t in items" :key="t.id" class="ios-row">
          <div class="ios-row-main">
            <span class="ios-row-title">
              {{ t.name }}
              <span v-if="t.is_external" class="ios-chip-warn ios-chip">外聘</span>
              <span v-if="t.is_grade_director" class="ios-chip-green ios-chip">年级主任</span>
            </span>
            <span class="ios-row-sub" style="margin-left: 8px">
              {{ t.subjects.map((s) => s.name).join('、') || '—' }}
              · {{ (t.grade_ids ?? []).map((g) => gradeLabel(g)).join('、') || '未填年级' }}
              · 基本课时 {{ t.base_periods }}
              · {{ t.admin_title ? `${t.admin_title}(减 ${t.admin_reduction})` : '无行政' }}
              · {{ t.user_id ? '已绑定帐号' : '无帐号' }}
            </span>
            <span :class="t.is_active ? 'ios-chip-green ios-chip' : 'ios-chip-gray ios-chip'" style="margin-left: 8px">
              {{ t.is_active ? '在职' : '离职' }}
            </span>
          </div>
          <n-button size="small" text type="primary" data-testid="teacher-edit" @click="openEdit(t)">编辑</n-button>
          <n-button size="small" text @click="openRules(t)">时段规则</n-button>
          <n-popconfirm @positive-click="remove(t)">
            <template #trigger>
              <n-button
                size="small" text type="error" data-testid="teacher-delete"
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
        </div>
      </template>
    </div>

    <n-modal v-model:show="show" preset="card" :title="editingId ? '编辑教师' : '新增教师'" style="max-width: 460px">
      <n-space vertical>
        <n-text>姓名</n-text>
        <n-input v-model:value="form.name" data-testid="teacher-name" placeholder="如:王小明" />
        <n-text>任教科目</n-text>
        <n-select v-model:value="form.subject_ids" multiple :options="subjectOptions" placeholder="可多选" />
        <n-text>所属年级</n-text>
        <n-select v-model:value="form.grade_ids" multiple :options="gradeOptions" placeholder="可多选,空 = 未填" />
        <n-space align="center">
          <n-text>设为年级主任</n-text>
          <n-switch v-model:value="form.is_grade_director" :disabled="!form.user_id || form.grade_ids.length === 0" />
          <n-text depth="3">主任管自己所属年级的排课;需先绑定登录账号并选所属年级</n-text>
        </n-space>
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
          <n-text depth="3" style="font-size: 12px">联系信息(选填,供调代课通知)</n-text>
        </n-divider>
        <n-space>
          <n-space vertical style="flex: 1">
            <n-text>Email</n-text>
            <n-input v-model:value="form.email" data-testid="teacher-email" placeholder="通知寄送用" />
          </n-space>
          <n-space vertical style="flex: 1">
            <n-text>手机</n-text>
            <n-input v-model:value="form.phone" placeholder="用于钉钉匹配与人工联系" />
          </n-space>
        </n-space>
        <!-- 手动侧只剩管理员恢复默认密码:帐号只读显示,不再提供手动绑定/建号/停用/自设密码 -->
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
            </n-space>
            <n-space v-if="auth.hasRole('admin')" align="center">
              <n-popconfirm @positive-click="onResetPassword">
                <template #trigger>
                  <n-button size="small" :loading="accountBusy" data-testid="teacher-reset-submit">
                    恢复默认密码
                  </n-button>
                </template>
                恢复为系统默认密码后,这位老师目前的登录状态会失效,下次登录必须自行改密码。确定恢复?
              </n-popconfirm>
            </n-space>
          </template>
          <template v-else>
            <n-text depth="3">无帐号:请通过导入建立(导入教师时自动建号,帐号=姓名,初始密码 admin)。</n-text>
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
