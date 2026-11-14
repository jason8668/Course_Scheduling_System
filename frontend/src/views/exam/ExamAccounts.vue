<script setup lang="ts">
import {
  NAlert, NButton, NDataTable, NEmpty, NInput, NModal, NSelect,
  NSpace, NText, useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { computed, h, onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import {
  PROVISION_ONCE_HINT, accountRoleLabel, buildCredentialCsv, listAccounts,
  provisionAccounts, resetAccountPassword,
} from '@/api/exam'
import type { AccountCredential, ExamAccount, ProvisionResult } from '@/api/exam'
import { listSemesters } from '@/api/semesters'
import type { SemesterListItem } from '@/api/semesters'

// 学生/家长账号开通管理页(KW-55):一键按学期开通学生/家长账号、账号清单、重置口令。
// 学生账号用户名=学号,家长账号用户名=家长手机号(同一手机号多子女只建一个账号)。
// 初始口令只在开通当次回传一次,已存在账号不回传口令;页面醒目提示,提供复制与
// 分发表导出,清除显示后无法再次查看。重置口令最短 8 位,重置后须改密。

const message = useMessage()

const semesters = ref<SemesterListItem[]>([])
const semesterId = ref<number | null>(null)
const filterRole = ref<string | null>(null)
const filterQ = ref('')
const accounts = ref<ExamAccount[]>([])
const total = ref(0)
const loading = ref(false)
const provisioning = ref(false)
const provisionResult = ref<ProvisionResult | null>(null)
const credentials = computed<AccountCredential[]>(() => provisionResult.value?.credentials ?? [])

const semesterOptions = computed(() =>
  semesters.value.map((s) => ({ label: s.label, value: s.id })),
)
const roleOptions = [
  { label: '学生', value: 'student' },
  { label: '家长', value: 'parent' },
]

const columns: DataTableColumns<ExamAccount> = [
  { title: '用户名', key: 'username', width: 160 },
  {
    title: '角色', key: 'role', width: 80,
    render: (row) => accountRoleLabel(row.role),
  },
  {
    title: '关联学生', key: 'student_names', width: 200,
    render: (row) => (row.student_names ?? []).join('、') || '—',
  },
  {
    title: '须改密', key: 'must_change_password', width: 80,
    render: (row) => (row.must_change_password ? '是' : '否'),
  },
  {
    title: '操作', key: 'actions', width: 200,
    render: (row) => h(NSpace, { size: 'small' }, {
      default: () => [
        h(NButton, { size: 'small', text: true, type: 'primary', onClick: () => openReset(row) }, () => '重置口令'),
      ],
    }),
  },
]

async function reloadAccounts() {
  loading.value = true
  try {
    const res = await listAccounts({
      semesterId: semesterId.value,
      role: filterRole.value,
      q: filterQ.value || undefined,
    })
    accounts.value = res.items
    total.value = res.total
  } catch (e) {
    message.error((e as ApiError).detail || '账号清单加载失败')
  } finally {
    loading.value = false
  }
}

async function onProvision() {
  if (!semesterId.value) { message.warning('请先选择学期'); return }
  showProvision.value = false
  provisioning.value = true
  try {
    provisionResult.value = await provisionAccounts(semesterId.value)
    const r = provisionResult.value
    message.success(`已开通:新建学生账号 ${r.students_created} 个,新建家长账号 ${r.parents_created} 个`)
    await reloadAccounts()
  } catch (e) {
    message.error((e as ApiError).detail || '账号开通失败')
  } finally {
    provisioning.value = false
  }
}

async function copyCredential(c: AccountCredential) {
  const text = `用户名:${c.username} 角色:${accountRoleLabel(c.role)} 学生:${c.student_name} 初始口令:${c.initial_password}`
  try {
    await navigator.clipboard.writeText(text)
    message.success('已复制该账号的初始口令')
  } catch {
    message.warning('复制失败,请手动记录')
  }
}

function downloadCsv() {
  const csv = buildCredentialCsv(credentials.value)
  const blob = new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'student_parent_credentials.csv'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
  message.success('分发表已导出')
}

function clearCredentials() {
  provisionResult.value = null
  message.success('初始口令显示已清除,无法再次查看')
}

// ── 重置口令:新口令最短 8 位,重置后须改密 ──
const showReset = ref(false)
const showProvision = ref(false)
const resetTarget = ref<ExamAccount | null>(null)
const newPassword = ref('')
function openReset(a: ExamAccount) {
  resetTarget.value = a
  newPassword.value = ''
  showReset.value = true
}
async function saveReset() {
  if (!resetTarget.value) return
  if (newPassword.value.length < 8) { message.warning('新口令至少需 8 个字符'); return }
  try {
    await resetAccountPassword(resetTarget.value.user_id, newPassword.value)
    showReset.value = false
    message.success(`已重置 ${resetTarget.value.username} 的口令,首次登录须改密`)
    await reloadAccounts()
  } catch (e) {
    message.error((e as ApiError).detail || '重置口令失败')
  }
}

onMounted(async () => {
  loading.value = true
  try {
    semesters.value = await listSemesters()
    const active = semesters.value.find((s) => s.status === 'active')
    semesterId.value = active ? active.id : (semesters.value[0]?.id ?? null)
    await reloadAccounts()
  } catch (e) {
    message.error((e as ApiError).detail || '加载失败')
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="ios-page">
    <h1 class="ios-title">学生/家长账号开通管理</h1>

    <!-- 一键开通(KW-55) -->
    <div class="ios-section">
      <div class="ios-section-title">一键开通账号</div>
      <div class="ios-card"><div class="ios-card-body">
        <n-space :wrap="true" align="center">
          <n-select
            v-model:value="semesterId" :options="semesterOptions" clearable
            placeholder="选择学期" style="width: 200px"
            data-testid="accounts-semester-select" @update:value="reloadAccounts"
          />
          <n-button
            type="primary" :loading="provisioning"
            data-testid="accounts-provision-btn" @click="showProvision = true"
          >一键开通本学期学生/家长账号</n-button>
        </n-space>
        <n-text depth="3" style="font-size: 12px; display: block; margin-top: 8px">
          学生账号用户名=学号;家长账号用户名=家长手机号,同一手机号多子女只建一个账号;首次登录须改密。
        </n-text>

        <n-alert
          v-if="provisionResult" type="warning" style="margin-top: 12px"
          data-testid="accounts-once-hint"
        >
          {{ PROVISION_ONCE_HINT }}:本次新建学生账号 {{ provisionResult.students_created }} 个,
          新建家长账号 {{ provisionResult.parents_created }} 个。
        </n-alert>
        <template v-if="credentials.length">
          <n-space :wrap="true" style="margin-top: 12px">
            <n-button data-testid="accounts-export-csv" @click="downloadCsv">导出分发表(CSV)</n-button>
            <n-button type="error" data-testid="accounts-clear-credentials" @click="clearCredentials">
              我已分发,清除口令显示
            </n-button>
          </n-space>
          <table class="ios-table" style="margin-top: 12px">
            <thead><tr><th>用户名</th><th>角色</th><th>学生</th><th>初始口令</th><th /></tr></thead>
            <tbody>
              <tr v-for="c in credentials" :key="c.username + c.role">
                <td>{{ c.username }}</td>
                <td>{{ accountRoleLabel(c.role) }}</td>
                <td>{{ c.student_name }}</td>
                <td>{{ c.initial_password }}</td>
                <td><n-button size="small" text type="primary" @click="copyCredential(c)">复制</n-button></td>
              </tr>
            </tbody>
          </table>
        </template>
        <n-text
          v-else-if="provisionResult" depth="3"
          style="font-size: 13px; display: block; margin-top: 12px"
        >
          本次没有新建账号(账号均已存在),无初始口令可分发。
        </n-text>
      </div></div>
    </div>

    <!-- 账号清单 -->
    <div class="ios-section">
      <div class="ios-section-title">账号清单</div>
      <div class="ios-card"><div class="ios-card-body">
        <n-space :wrap="true" align="center">
          <n-select
            v-model:value="filterRole" :options="roleOptions" clearable
            placeholder="全部角色" style="width: 130px" @update:value="reloadAccounts"
          />
          <n-input
            v-model:value="filterQ" placeholder="按用户名或学生姓名检索" clearable
            style="width: 220px" @change="reloadAccounts"
          />
          <n-button type="primary" @click="reloadAccounts">检索</n-button>
        </n-space>
        <n-empty v-if="!loading && accounts.length === 0" description="暂无学生/家长账号" style="margin-top: 12px" />
        <n-data-table
          v-else :columns="columns" :data="accounts" :loading="loading"
          :bordered="false" :single-line="false" style="margin-top: 12px"
        />
        <n-text depth="3" style="font-size: 13px">共 {{ total }} 个账号(清单里不显示初始口令)</n-text>
      </div></div>
    </div>

    <!-- 一键开通二次确认 -->
    <n-modal v-model:show="showProvision" preset="card" title="一键开通账号" style="max-width: 480px">
      <n-space vertical>
        <n-text>按学期为在读学生与家长开通账号;已存在账号跳过不重复建。初始口令只显示一次,请立即分发。</n-text>
        <n-button type="primary" data-testid="accounts-provision-confirm" @click="onProvision">确定开通</n-button>
      </n-space>
    </n-modal>

    <!-- 重置口令 -->
    <n-modal v-model:show="showReset" preset="card" title="重置账号口令" style="max-width: 480px">
      <n-space vertical>
        <n-text>账号 {{ resetTarget?.username }}({{ resetTarget ? accountRoleLabel(resetTarget.role) : '' }})</n-text>
        <n-alert type="warning">重置后首次登录须改密,请把新口令当面或单独发给本人,不要发到群里。</n-alert>
        <n-text>新口令(至少 8 个字符)</n-text>
        <n-input v-model:value="newPassword" type="password" placeholder="新口令" />
        <n-button type="primary" data-testid="accounts-reset-confirm" @click="saveReset">确认重置</n-button>
      </n-space>
    </n-modal>
  </div>
</template>
