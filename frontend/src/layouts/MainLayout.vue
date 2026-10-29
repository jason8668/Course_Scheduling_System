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
  const my = { label: menuLink('my', '我的'), key: 'my' }
  const dashboard = { label: menuLink('dashboard', '仪表板'), key: 'dashboard' }
  const schoolCalendar = { label: menuLink('school-calendar', '学校校历'), key: 'school-calendar' }
  // 纯教师帐号:只列已重排的三页(我的/仪表板/学校校历)。
  // 课表查询、请假登记、我的代课课时尚未重排,菜单隐藏,路由保留。
  if (!canManage.value) return [my, dashboard, schoolCalendar]
  return [
    dashboard,
    schoolCalendar,
    {
      label: '基础资料',
      key: 'basedata-group',
      children: [
        { label: menuLink('setup-flow', '开学建置'), key: 'setup-flow' },
        { label: menuLink('basedata', '教师/班级/科目/场地'), key: 'basedata' },
      ],
    },
    {
      label: '排课作业',
      key: 'scheduling-group',
      children: [
        { label: menuLink('scheduling-center', '排课中心'), key: 'scheduling-center' },
      ],
    },
    {
      label: '调代课',
      key: 'substitution-group',
      children: [
        { label: menuLink('substitution-center', '调代课中心'), key: 'substitution-center' },
        { label: menuLink('stats-center', '统计中心'), key: 'stats-center' },
      ],
    },
    { label: menuLink('system', '系统管理'), key: 'system' },
  ]
})

const activeKey = computed(() => route.name as string)

// 边栏 iOS 毛玻璃配色:亮底 + 苹果蓝选中态,深色字,分组标题灰字。
// 注意:Naive 菜单本身背景默认透明,真正的不透明层是 sider 的底色,
// 所以透明度由 sider 的 rgba 控制,不是菜单。
const menuThemeOverrides = {
  color: 'rgba(255, 255, 255, 0)',
  groupTextColor: 'rgba(60, 60, 67, 0.6)',
  itemTextColor: '#1c1c1e',
  itemTextColorHover: '#1c1c1e',
  itemTextColorActive: '#007aff',
  itemTextColorChildActive: '#007aff',
  itemColorHover: 'rgba(0, 0, 0, 0.04)',
  itemColorActive: 'rgba(0, 122, 255, 0.12)',
  itemColorActiveHover: 'rgba(0, 122, 255, 0.16)',
  arrowColor: 'rgba(60, 60, 67, 0.6)',
  arrowColorHover: '#007aff',
  arrowColorActive: '#007aff',
}

// 菜单显隐规则(Jason 2026-10-29 定):菜单只列已按 iOS 语言重排的页,
// 未重排的旧页不显示(路由保留,直接输地址仍能进,功能没删);
// 重排完一块,再把它的入口放回菜单。不要把所有目录都打开,
// 否则看不出哪些写了、哪些没写。
// 已重排:我的 / 仪表板 / 学校校历 / 开学建置 / 教师班级科目场地 /
// 排课中心 / 调代课中心 / 统计中心 / 系统管理。
// 未重排(菜单隐藏):学期与节次表 / 配课管理 / 排课工作台 / 自动排课 /
// 版本与发布 / 课表查询 / 请假登记 / 调代课处理 / 今日调代课 /
// 调代课纪录 / 代课课时统计 / 教学课时统计 / 通知确认看板。

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
      style="background: rgba(255, 255, 255, 0.55); -webkit-backdrop-filter: saturate(180%) blur(24px); backdrop-filter: saturate(180%) blur(24px); border-right: 1px solid rgba(0, 0, 0, 0.06)"
      :collapsed-width="64"
      :width="220"
      show-trigger
      :collapsed="collapsed"
      @collapse="collapsed = true"
      @expand="collapsed = false"
    >
      <div style="padding: 18px 16px; font-weight: 700; font-size: 19px; letter-spacing: -0.5px; color: #000; white-space: nowrap; overflow: hidden">
        {{ collapsed ? '排课' : '排课与调代课系统' }}
      </div>
      <n-menu
        :value="activeKey"
        :collapsed="collapsed"
        :collapsed-width="64"
        :options="menuOptions"
        :theme-overrides="menuThemeOverrides"
        :default-expanded-keys="['basedata-group', 'scheduling-group']"
      />
      <div v-if="version && !collapsed" class="version" data-testid="app-version">
        版本 {{ version }}
      </div>
    </n-layout-sider>

    <n-layout>
      <n-layout-header class="app-header" style="padding: 12px 24px; background: rgba(255, 255, 255, 0.65); -webkit-backdrop-filter: saturate(180%) blur(24px); backdrop-filter: saturate(180%) blur(24px); box-shadow: 0 1px 0 rgba(0, 0, 0, 0.06)">
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
.version { padding: 12px 20px; font-size: 12px; color: rgba(60, 60, 67, 0.6); }
.update-link { text-decoration: none; }
</style>
