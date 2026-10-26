<script setup lang="ts">
import { NButton, NLayout, NLayoutContent, NLayoutHeader, NLayoutSider, NMenu, NSpace, NTag, NText } from 'naive-ui'
import { computed, h, onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import NotificationBell from '@/components/NotificationBell.vue'
import { getUpdateStatus, getVersion } from '@/api/system'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const ROLE_LABELS: Record<string, string> = {
  admin: '系统管理员',
  director: '教务主任',
  scheduler: '教学组长',
  teacher: '教师',
}
const roleLabels = computed(() => (auth.user?.roles ?? []).map((r) => ROLE_LABELS[r] ?? r))

// 手机尺寸默认收合侧边栏:390px 宽的萤幕若被 220px 侧栏占去,课表几乎没有空间
const collapsed = ref(typeof window !== 'undefined' && window.innerWidth < 768)

function menuLink(name: string, label: string) {
  return () => h(RouterLink, { to: { name } }, { default: () => label })
}

// 纯教师帐号只看得到课表查询(其余页面的后端 API 需主任以上权限)
const canManage = computed(() =>
  auth.hasRole('admin') || auth.hasRole('director'))

const menuOptions = computed(() => {
  const query = { label: menuLink('timetable-query', '课表查询'), key: 'timetable-query' }
  // 请假是教师自己要做的事,纯教师帐号也看得到
  const leaves = { label: menuLink('leaves', '请假登记'), key: 'leaves' }
  // 教师可查自己的代课课时
  const myStats = { label: menuLink('substitution-stats', '我的代课课时'), key: 'substitution-stats' }
  const dashboard = { label: menuLink('dashboard', '仪表板'), key: 'dashboard' }
  const schoolCalendar = { label: menuLink('school-calendar', '学校校历'), key: 'school-calendar' }
  if (!canManage.value) return [dashboard, query, schoolCalendar, leaves, myStats]
  return [
    dashboard,
    schoolCalendar,
    query,
    {
      label: '基础资料',
      key: 'basedata-group',
      children: [
        { label: menuLink('semesters', '学期与节次表'), key: 'semesters' },
        { label: menuLink('basedata', '教师/班级/科目/场地'), key: 'basedata' },
      ],
    },
    {
      label: '排课作业',
      key: 'scheduling-group',
      children: [
        { label: menuLink('assignments', '配课管理'), key: 'assignments' },
        { label: menuLink('workbench', '排课工作台'), key: 'workbench' },
        { label: menuLink('auto-schedule', '自动排课'), key: 'auto-schedule' },
        { label: menuLink('versions', '版本与发布'), key: 'versions' },
        { label: menuLink('timetable-demo', '课表元件(示范)'), key: 'timetable-demo' },
      ],
    },
    {
      label: '调代课',
      key: 'substitution-group',
      children: [
        leaves,
        { label: menuLink('substitutions', '调代课处理'), key: 'substitutions' },
        { label: menuLink('daily-board', '今日调代课'), key: 'daily-board' },
        { label: menuLink('substitution-log', '调代课纪录'), key: 'substitution-log' },
        { label: menuLink('substitution-stats', '代课课时统计'), key: 'substitution-stats' },
        { label: menuLink('teaching-hours', '教学课时统计'), key: 'teaching-hours' },
        { label: menuLink('notification-board', '通知确认看板'), key: 'notification-board' },
      ],
    },
    { label: menuLink('system', '系统管理'), key: 'system' },
    ...(auth.hasRole('admin')
      ? [{ label: menuLink('user-grades', '账号年级'), key: 'user-grades' }]
      : []),
  ]
})

const activeKey = computed(() => route.name as string)

// 版本号:回报问题时要知道对方是哪一版;升级后也靠它确认升级成功
const version = ref('')
// 有新版本时只提醒管理员(升级是管理员的事,别让教师看了紧张)
const newVersion = ref('')
onMounted(async () => {
  try {
    version.value = (await getVersion()).version
    if (auth.hasRole('admin')) {
      const st = await getUpdateStatus()
      if (st.update_available) newVersion.value = st.latest
    }
  } catch {
    // 版本信息只是辅助,取不到不影响任何功能
  }
})

function onChangePassword() {
  router.push({ name: 'change-password' })
}

async function onLogout() {
  await auth.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <n-layout has-sider style="height: 100vh">
    <n-layout-sider
      collapse-mode="width"
      style="background: linear-gradient(180deg, #082f42 0%, #0d5a6e 100%)"
      :collapsed-width="64"
      :width="220"
      show-trigger
      :collapsed="collapsed"
      @collapse="collapsed = true"
      @expand="collapsed = false"
    >
      <div style="padding: 18px 16px; font-weight: 700; font-size: 16px; letter-spacing: 1px; color: #fff; white-space: nowrap; overflow: hidden">
        {{ collapsed ? '排课' : '排课与调代课系统' }}
      </div>
      <n-menu
        inverted
        :value="activeKey"
        :collapsed="collapsed"
        :collapsed-width="64"
        :options="menuOptions"
        :default-expanded-keys="['basedata-group', 'scheduling-group']"
      />
      <div v-if="version && !collapsed" class="version" data-testid="app-version">
        版本 {{ version }}
      </div>
    </n-layout-sider>

    <n-layout>
      <n-layout-header style="padding: 12px 24px; background: #fff; box-shadow: 0 1px 6px rgba(8, 47, 66, 0.07)">
        <n-space justify="end" align="center">
          <router-link
            v-if="newVersion" :to="{ name: 'system' }" class="update-link"
            data-testid="update-badge"
          >
            <n-tag type="warning" size="small" round>有新版本 {{ newVersion }}</n-tag>
          </router-link>
          <notification-bell />
          <n-text v-if="auth.user">{{ auth.user.display_name }}</n-text>
          <n-tag v-for="label in roleLabels" :key="label" type="info" size="small">
            {{ label }}
          </n-tag>
          <n-button size="small" data-testid="header-change-password" @click="onChangePassword">
            修改密码
          </n-button>
          <n-button size="small" @click="onLogout">退出登录</n-button>
        </n-space>
      </n-layout-header>

      <n-layout-content content-style="padding: 24px" style="background: transparent">
        <router-view />
      </n-layout-content>
    </n-layout>
  </n-layout>
</template>

<style scoped>
.version { padding: 12px 20px; font-size: 12px; color: rgba(255, 255, 255, 0.65); }
.update-link { text-decoration: none; }
</style>
