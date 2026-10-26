// 账号年级(仅管理员):三种角色——管理员、年级主任、普通老师。
// 任命方式:管理员在这里给老师帐号配年级,配了即授予该年级的主任权限(自动带上
// 主任身份),可排那个年级的课(配课、工作台格位、自动排课范围、调课处置均按此
// 拦截)并可发布课表;不配年级就没有排课权限,只能当任课老师用。空 = 无排课权限。
// 只有管理员不受年级限制。

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { NButton, NSelect, NSpace, NText, useMessage } from 'naive-ui'

import { gradeLabel } from '@/api/substitutionLog'
import { listUsersWithGrades, setUserGrades, type UserGradeItem } from '@/api/userGrades'

const message = useMessage()
const users = ref<UserGradeItem[]>([])
const drafts = ref<Record<number, number[]>>({})
const saving = ref<Record<number, boolean>>({})

const gradeOptions = Array.from({ length: 12 }, (_, i) => ({
  label: gradeLabel(i + 1), value: i + 1,
}))
const roleLabels: Record<string, string> = {
  admin: '系统管理员', director: '教务主任', scheduler: '教学组长', teacher: '教师',
}

async function load() {
  try {
    users.value = await listUsersWithGrades()
    drafts.value = Object.fromEntries(users.value.map((u) => [u.id, [...u.grades]]))
  } catch {
    message.error('无法载入账号一览')
  }
}

async function save(u: UserGradeItem) {
  saving.value[u.id] = true
  try {
    const grades = await setUserGrades(u.id, drafts.value[u.id] ?? [])
    u.grades = grades
    drafts.value[u.id] = [...grades]
    message.success(`「${u.username}」年级已更新${grades.length ? '' : '(无排课权限)'}`)
  } catch {
    message.error('保存失败')
  } finally {
    saving.value[u.id] = false
  }
}

function dirty(u: UserGradeItem) {
  const d = drafts.value[u.id] ?? []
  return d.length !== u.grades.length || d.some((g, i) => g !== [...u.grades].sort((a, b) => a - b)[i])
}

onMounted(load)
</script>

<template>
  <n-space vertical>
    <n-text depth="3">
      管理员给老师配年级就是任命:配了年级就是该年级的主任,可排该年级的课并可发布
      课表;不配年级就没有排课权限,只能当任课老师用。只有管理员不受年级限制。
    </n-text>
    <table class="user-grades-table">
      <thead>
        <tr><th>账号</th><th>姓名</th><th>角色</th><th>可操作年级(空 = 无排课权限)</th><th>操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="u in users" :key="u.id">
          <td>{{ u.username }}</td>
          <td>{{ u.display_name || '—' }}</td>
          <td>{{ u.roles.map((r) => roleLabels[r] ?? r).join('、') }}</td>
          <td style="min-width: 280px">
            <n-select
              v-model:value="drafts[u.id]" multiple :options="gradeOptions"
              placeholder="空 = 无排课权限" clearable
              :disabled="u.roles.includes('admin')"
            />
          </td>
          <td>
            <n-button
              size="small" type="primary" :disabled="!dirty(u)" :loading="saving[u.id]"
              @click="save(u)"
            >
              保存
            </n-button>
          </td>
        </tr>
      </tbody>
    </table>
    <n-text v-if="users.length === 0" depth="3">尚无账号</n-text>
  </n-space>
</template>

<style scoped>
.user-grades-table { border-collapse: collapse; width: 100%; }
.user-grades-table th, .user-grades-table td {
  border: 1px solid #e5e5e5; padding: 8px 10px; text-align: left;
}
</style>
