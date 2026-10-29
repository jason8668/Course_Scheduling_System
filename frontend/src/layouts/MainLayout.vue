<script setup lang="ts">
import { NButton, NLayout, NLayoutContent, NLayoutHeader, NLayoutSider, NMenu, NSpace, NTag, NText } from 'naive-ui'
import type { MenuOption } from 'naive-ui'
import { computed, h, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
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

const menuOptions = computed<MenuOption[]>(() => {
  const my = { label: menuLink('my', '我的'), key: 'my' }
  const dashboard = { label: menuLink('dashboard', '仪表板'), key: 'dashboard' }
  const query = { label: menuLink('timetable-query', '课表查询'), key: 'timetable-query' }
  const leaves = { label: menuLink('leaves', '请假登记'), key: 'leaves' }
  // 校历(Jason 2026-10-29 定):不再单列菜单模块,改走顶栏右上角「校历」按钮,路由保留。
  // 纯教师帐号:只列已重排的四页。我的代课课时尚未重排,菜单隐藏,路由保留。
  if (!canManage.value) return [my, dashboard, query, leaves]
  return [
    dashboard,
    query,
    {
      label: '基础资料',
      key: 'basedata-group',
      // Mac 式扁平分组:小标题 + 下面平铺条目,不缩进、不折叠、不带箭头。
      // Finder 边栏就是这样:分组标题只是灰色小字,不是可点开合的父目录。
      type: 'group',
      children: [
        { label: menuLink('setup-flow', '开学建置'), key: 'setup-flow' },
        { label: menuLink('basedata', '教师/班级/科目/场地'), key: 'basedata' },
      ],
    },
    {
      label: '排课作业',
      key: 'scheduling-group',
      type: 'group',
      children: [
        { label: menuLink('scheduling-center', '排课中心'), key: 'scheduling-center' },
      ],
    },
    {
      label: '调代课',
      key: 'substitution-group',
      type: 'group',
      children: [
        { label: menuLink('substitution-center', '调代课中心'), key: 'substitution-center' },
        { label: menuLink('stats-center', '统计中心'), key: 'stats-center' },
        leaves,
        { label: menuLink('daily-board', '今日调代课'), key: 'daily-board' },
        { label: menuLink('substitution-log', '调代课纪录'), key: 'substitution-log' },
        { label: menuLink('substitution-stats', '代课课时统计'), key: 'substitution-stats' },
        { label: menuLink('teaching-hours', '教学课时统计'), key: 'teaching-hours' },
        { label: menuLink('notification-board', '通知确认看板'), key: 'notification-board' },
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
  // 选中底色由滑动指示条(半透明圆角框)负责,Naive 自带的选中底色须透明,
  // 否则两层底色叠加,看不出框在移动。
  itemColorActive: 'rgba(255, 255, 255, 0)',
  itemColorActiveHover: 'rgba(255, 255, 255, 0)',
  arrowColor: 'rgba(60, 60, 67, 0.6)',
  arrowColorHover: '#007aff',
  arrowColorActive: '#007aff',
}

// 菜单显隐规则(Jason 2026-10-29 定):菜单只列已按 iOS 语言重排的页,
// 未重排的旧页不显示(路由保留,直接输地址仍能进,功能没删);
// 重排完一块,再把它的入口放回菜单。不要把所有目录都打开,
// 否则看不出哪些写了、哪些没写。
// 已重排:我的 / 仪表板 / 开学建置 / 教师班级科目场地 /
// 排课中心 / 调代课中心 / 统计中心 / 系统管理 / 课表查询 / 请假登记 /
// 今日调代课 / 调代课纪录 / 代课课时统计 / 教学课时统计 / 通知确认看板。
// 校历已重排,但 Jason 定为顶栏按钮(不在菜单里单列模块)。
// 未重排(菜单隐藏):学期与节次表 / 配课管理 / 排课工作台 / 自动排课 /
// 版本与发布 / 调代课处理。

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

// ── 滑动选中指示条(Jason 2026-10-29 要的 Mac/iOS 效果) ──
// 点击菜单时,一个半透明圆角框从当前条目滑动到目标条目,而不是选中态瞬间跳变。
// 实现:量选中条目的位置,把一个绝对定位的透明框移到那里,top/height 用 CSS 过渡动画。
// Naive 自带的选中底色已在 theme-overrides 里设透明,避免两层叠加。
const menuWrapRef = ref<HTMLElement | null>(null)
const indicatorTop = ref(0)
const indicatorHeight = ref(0)
const indicatorVisible = ref(false)
const indicatorReady = ref(false)
const indicatorStyle = computed(() => ({
  top: `${indicatorTop.value}px`,
  height: `${indicatorHeight.value}px`,
  opacity: indicatorVisible.value ? 1 : 0,
  transition: indicatorReady.value
    ? 'top 0.35s cubic-bezier(0.2, 0.8, 0.2, 1), height 0.35s cubic-bezier(0.2, 0.8, 0.2, 1), opacity 0.2s'
    : 'none',
}))
function updateIndicator() {
  const wrap = menuWrapRef.value
  if (!wrap) return
  // 选中条目的类名是 Naive 的 n-menu-item-content--selected(源码确认)。
  const el = wrap.querySelector('.n-menu-item-content--selected') as HTMLElement | null
  if (!el) {
    // 当前路由不在菜单里(例如被隐藏的旧页):指示条淡出,不指任何条目。
    indicatorVisible.value = false
    return
  }
  const wrapRect = wrap.getBoundingClientRect()
  const rect = el.getBoundingClientRect()
  indicatorTop.value = rect.top - wrapRect.top
  indicatorHeight.value = rect.height
  indicatorVisible.value = true
  if (!indicatorReady.value) {
    // 首帧先定位、不滑动,下一帧再开启动画,避免一进页面框从顶部飞下来。
    requestAnimationFrame(() => { indicatorReady.value = true })
  }
}
watch([activeKey, collapsed], () => nextTick(updateIndicator))
onMounted(() => {
  nextTick(updateIndicator)
  window.addEventListener('resize', updateIndicator)
})
onBeforeUnmount(() => window.removeEventListener('resize', updateIndicator))

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
      style="background: rgba(255, 255, 255, 0.5); -webkit-backdrop-filter: saturate(180%) blur(24px); backdrop-filter: saturate(180%) blur(24px); border: 1px solid rgba(255, 255, 255, 0.7); border-radius: 20px; margin: 12px 0 12px 12px; box-shadow: 0 8px 30px rgba(0, 0, 0, 0.08)"
      :collapsed-width="64"
      :width="220"
      show-trigger
      :collapsed="collapsed"
      @collapse="collapsed = true"
      @expand="collapsed = false"
    >
      <!-- 边栏悬浮圆角玻璃(Jason 2026-10-29 照片定的 Liquid Glass 效果):
        不再是贴满左边的整列,而是一块圆角玻璃板悬浮在页面底色上——
        四周留 12px 缝隙、20px 圆角、半透明 + 模糊 + 柔和阴影,
        就像控制中心里一块玻璃小组件盖在壁纸上。收合后同样是一块窄玻璃板。 -->
      <div style="padding: 18px 16px; font-weight: 700; font-size: 19px; letter-spacing: -0.5px; color: #000; white-space: nowrap; overflow: hidden">
        {{ collapsed ? '排课' : '排课与调代课系统' }}
      </div>
      <div ref="menuWrapRef" class="sider-menu-wrap">
        <div class="menu-indicator" :style="indicatorStyle" />
        <n-menu
          :value="activeKey"
          :collapsed="collapsed"
          :collapsed-width="64"
          :options="menuOptions"
          :theme-overrides="menuThemeOverrides"
          :default-expanded-keys="['basedata-group', 'scheduling-group']"
        />
      </div>
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
          <n-button
            text type="primary" size="small" data-testid="header-calendar"
            @click="router.push({ name: 'school-calendar' })"
          >
            校历
          </n-button>
          <notification-bell />
          <n-text v-if="auth.user">{{ auth.user.display_name }}</n-text>
          <n-tag v-for="label in roleLabels" :key="label" type="info" size="small">
            {{ label }}
          </n-tag>
          <n-button text size="small" data-testid="header-change-password" @click="onChangePassword">
            修改密码
          </n-button>
          <n-button text size="small" @click="onLogout">退出登录</n-button>
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
/* 滑动指示条:半透明圆角框,左右各留 8px 边距,像 Mac 边栏选中态那样不贴边。 */
.sider-menu-wrap { position: relative; }
.menu-indicator {
  position: absolute; left: 8px; right: 8px;
  border-radius: 10px; background: rgba(0, 122, 255, 0.12);
  pointer-events: none;
}
/* 菜单整体抬到指示条上方(菜单底色透明),文字压在框上,框只当底色。 */
.sider-menu-wrap :deep(.n-menu) { position: relative; z-index: 1; }
</style>
