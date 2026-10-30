<script setup lang="ts">
import { NButton, NDrawer, NDrawerContent, NLayout, NLayoutContent, NLayoutHeader, NLayoutSider, NMenu, NSpace, NTag, NText } from 'naive-ui'
import type { MenuOption } from 'naive-ui'
import { computed, h, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
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
// 顶栏只显示一次:管理员帐号的显示名本身就是「系统管理员」,与角色标签重字,
// 重的那个不画,只留与名字不同的角色(例如教务主任)。
const otherRoleLabels = computed(() => roleLabels.value.filter((l) => l !== auth.user?.display_name))

// 手机尺寸默认收合侧边栏:390px 宽的萤幕若被 220px 侧栏占去,课表几乎没有空间
const collapsed = ref(typeof window !== 'undefined' && window.innerWidth < 768)
// 手机适配(2026-10-30 菜单精简+手机适配):窄屏不再留 80px 收合边栏占地方,
// 边栏改成抽屉——平时完全不占屏,点左上角菜单钮才滑出来,选完自动收回。
// 桌面端仍用原来的悬浮玻璃边栏,逻辑不动。
const isMobile = ref(typeof window !== 'undefined' && window.innerWidth < 768)
const drawerOpen = ref(false)
function onResize() {
  isMobile.value = window.innerWidth < 768
  if (!isMobile.value) drawerOpen.value = false
}

// 收合后看不到的根因(Jason 2026-10-30 截图):菜单项原来没有图标,
// 标签又是 RouterLink 组件不是纯文字,Naive 收合模式下悬浮提示取不到文字,
// 只剩一个空方块,点都不知道点的是哪页。
// 修复:标签改回纯文字(收合提示能正常显示),收合时每项显示前两字小方块,
// 展开时隐藏、外观与原来一致;点选改走 router.push,不再靠 RouterLink。
// 前两字(Jason 2026-10-30 再定:一个字太小看不清,改成两个字、字调大,
// 例如仪表板→仪表、课表查询→课表,64px 收合宽放得下)。
function menuItem(key: string, label: string): MenuOption {
  return {
    label,
    key,
    icon: () => h('span', { class: 'menu-char-icon' }, label.slice(0, 2)),
  }
}
function onMenuSelect(key: string) {
  if (key.endsWith('-group')) return
  drawerOpen.value = false
  router.push({ name: key })
}

// 纯教师帐号只看得到课表查询(其余页面的后端 API 需主任以上权限)
const canManage = computed(() =>
  auth.hasRole('admin') || auth.hasRole('director'))

const menuOptions = computed<MenuOption[]>(() => {
  // 「我的」已并进仪表板(2026-10-30 Jason 定):教师菜单不再单列「我的」,
  // 路由 /my 改重定向到仪表板,旧通知里的 /my 链接落点仍在仪表板,不会断。
  const dashboard = menuItem('dashboard', '仪表板')
  const query = menuItem('timetable-query', '课表查询')
  const leaves = menuItem('leaves', '调课管理')
  // 校历(Jason 2026-10-29 定):不再单列菜单模块,改走顶栏右上角「校历」按钮,路由保留。
  // 仪表板与课表查询(Jason 2026-10-29 23:59 定):两个都要在菜单里,缺一不可——
  // 之前把课表查询移出菜单、把仪表板改名首页,他找不到,作废,全部调回来。
  // 纯教师帐号:只列已重排的三页(仪表板已含原「我的」全部功能)。
  if (!canManage.value) return [dashboard, query, leaves]
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
        menuItem('setup-flow', '开学建置'),
        menuItem('semesters', '学期与节次表'),
        menuItem('basedata', '基础数据'),
      ],
    },
    menuItem('scheduling-center', '排课中心'),
    {
      label: '调代课',
      key: 'substitution-group',
      type: 'group',
      children: [
        menuItem('substitution-center', '调代课中心'),
        leaves,
        menuItem('substitutions', '调代课处理'),
        // 今日调代课退出菜单(2026-10-30 菜单精简):当日看板的内容已在调代课中心
        // (当日已安排/请假人数 + 待处理),入口改放调代课中心顶部的「今日看板」按钮,
        // 路由保留,直接输地址仍能进,功能没删。
        menuItem('substitution-log', '调代课纪录'),
      ],
    },
    // 统计中心单列顶层:统计组只剩它一个孩子,成组就是多余一层(与排课中心同例)。
    menuItem('stats-center', '统计中心'),
    menuItem('system', '系统管理'),
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
// 已重排:我的 / 仪表板 / 开学建置 / 学期与节次表 / 基础数据 /
// 排课中心 / 调代课中心 / 统计中心 / 系统管理 / 课表查询 / 请假登记 /
// 调代课处理 / 今日调代课 / 调代课纪录 / 代课课时统计 / 教学课时统计 /
// 通知确认看板。
// 菜单分组(Jason 2026-10-29 定):调代课组拆为调代课 + 统计两组;
// 统计去重(Jason 2026-10-30 定:按构思做,简单明了):统计中心已覆盖
// 代课课时统计/教学课时统计/通知确认看板的功能,三页退出菜单(路由保留,
// 直接输地址仍能进,功能没删);统计组只剩统计中心一个孩子,成组多余一层,
// 故统计中心单列顶层(与排课中心同例)。
// 仪表板不再挂「查看完整课表」入口卡:课表查询已回菜单,挂着就是多余一处
// (Jason 2026-10-30 定:内容不冗余,能简单尽量简单)。
// 校历已重排,但 Jason 定为顶栏按钮(不在菜单里单列模块)。
// 排课旧页(配课管理 / 排课工作台 / 自动排课 / 版本与发布)功能已由排课中心
// 覆盖,不再放回菜单,路由保留(直接输地址仍能进)。

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
  window.addEventListener('resize', onResize)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', updateIndicator)
  window.removeEventListener('resize', onResize)
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
  <n-layout
    has-sider
    style="height: 100vh; background: linear-gradient(180deg, #C7D9F6 0%, #DDE7F8 30%, #E9EBF2 65%, #F5F5F7 100%)"
  >
    <n-layout-sider
      v-if="!isMobile"
      collapse-mode="width"
      style="background: linear-gradient(180deg, rgba(255, 255, 255, 0.60), rgba(255, 255, 255, 0.35)); -webkit-backdrop-filter: saturate(180%) blur(24px); backdrop-filter: saturate(180%) blur(24px); border: 1px solid rgba(255, 255, 255, 0.9); border-radius: 20px; margin: 12px 0 12px 12px; box-shadow: 0 12px 40px rgba(30, 60, 120, 0.16), inset 0 1px 0 rgba(255, 255, 255, 0.95)"
      :collapsed-width="80"
      :width="220"
      show-trigger
      :collapsed="collapsed"
      @collapse="collapsed = true"
      @expand="collapsed = false"
    >
      <!-- 边栏悬浮圆角玻璃(Jason 2026-10-29 照片定的 Liquid Glass 效果):
        不再是贴满左边的整列,而是一块圆角玻璃板悬浮在页面底色上——
        四周留 12px 缝隙、20px 圆角、上亮下暗的玻璃渐变 + 顶部内高光 + 柔和阴影。
        玻璃要透出东西才像玻璃:应用壳底色改成顶部淡蓝到底部灰白的渐变,
        面板透过模糊把这层淡蓝晕进来,而不是对著一块平色底发呆。
        收合后同样是一块窄玻璃板。 -->
      <div style="padding: 18px 16px; font-weight: 700; font-size: 19px; letter-spacing: -0.5px; color: #000; white-space: nowrap; overflow: hidden">
        {{ collapsed ? '排课' : '排课与调代课系统' }}
      </div>
      <div ref="menuWrapRef" class="sider-menu-wrap">
        <div class="menu-indicator" :style="indicatorStyle" />
        <n-menu
          :value="activeKey"
          :collapsed="collapsed"
          :collapsed-width="80"
          :options="menuOptions"
          :theme-overrides="menuThemeOverrides"
          :default-expanded-keys="['basedata-group']"
          @update:value="onMenuSelect"
        />
      </div>
      <div v-if="version && !collapsed" class="version" data-testid="app-version">
        版本 {{ version }}
      </div>
    </n-layout-sider>

    <n-layout style="background: transparent">
      <n-layout-header class="app-header" style="padding: 12px 24px; background: linear-gradient(180deg, rgba(255, 255, 255, 0.75), rgba(255, 255, 255, 0.5)); -webkit-backdrop-filter: saturate(180%) blur(24px); backdrop-filter: saturate(180%) blur(24px); box-shadow: 0 1px 0 rgba(0, 0, 0, 0.06), inset 0 1px 0 rgba(255, 255, 255, 0.8)">
        <div style="display: flex; justify-content: space-between; align-items: center; width: 100%">
          <n-button v-if="isMobile" text size="large" data-testid="header-menu" @click="drawerOpen = true">
            ☰ 菜单
          </n-button>
          <span v-else />
          <n-space align="center">
          <router-link
            v-if="newVersion" :to="{ name: 'system' }" class="update-link"
            data-testid="update-badge"
          >
            <n-tag type="warning" size="small" round>有新版本 {{ newVersion }}</n-tag>
          </router-link>
          <n-button
            class="glass-btn" size="small" data-testid="header-calendar"
            @click="router.push({ name: 'school-calendar' })"
          >
            校历
          </n-button>
          <notification-bell />
          <n-text v-if="auth.user">{{ auth.user.display_name }}</n-text>
          <span v-for="label in otherRoleLabels" :key="label" class="ios-chip">{{ label }}</span>
          <n-button text size="small" data-testid="header-change-password" @click="onChangePassword">
            修改密码
          </n-button>
          <n-button text size="small" @click="onLogout">退出登录</n-button>
          </n-space>
        </div>
      </n-layout-header>

      <n-layout-content :content-style="isMobile ? 'padding: 12px' : 'padding: 24px'" style="background: transparent">
        <router-view />
      </n-layout-content>
    </n-layout>
  </n-layout>

  <!-- 手机抽屉菜单:窄屏才出现,点选后自动收回 -->
  <n-drawer v-model:show="drawerOpen" placement="left" :width="260" data-testid="mobile-menu-drawer">
    <n-drawer-content title="排课与调代课系统">
      <n-menu
        :value="activeKey"
        :options="menuOptions"
        :theme-overrides="menuThemeOverrides"
        @update:value="onMenuSelect"
      />
    </n-drawer-content>
  </n-drawer>
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
/* 收合两字图标:展开时隐藏(外观与原来一致),收合时显示前两字,光看方块也能认出是哪页。
   2026-10-30 截图教训:64px 收合宽里塞 44px 徽章 + 左右边距,两个字被挤成上下两行,
   根本没法看。修法:收合宽放宽到 80px;徽章 white-space: nowrap 绝不换行;
   图标格本身定宽 48px 且不收缩,菜单项内容居中、左右内边距清零,
   这样两个字永远横排一行,悬浮提示仍显示全名,认得出是哪页。 */
.sider-menu-wrap :deep(.menu-char-icon) { display: none; }
.sider-menu-wrap :deep(.n-menu--collapsed .n-menu-item-content) {
  display: flex; justify-content: center; padding-left: 0; padding-right: 0;
}
.sider-menu-wrap :deep(.n-menu--collapsed .n-menu-item-content__icon) {
  width: 48px; flex-shrink: 0; margin-right: 0;
}
.sider-menu-wrap :deep(.n-menu--collapsed .menu-char-icon) {
  display: inline-flex; align-items: center; justify-content: center;
  width: 48px; height: 28px; border-radius: 8px; flex-shrink: 0;
  white-space: nowrap; overflow: hidden;
  background: rgba(0, 122, 255, 0.12); color: #007aff;
  font-size: 15px; font-weight: 600;
}
/* 顶栏校历毛玻璃药丸按钮:光看两个字没人知道能按,做成圆角玻璃片才像按钮。
   上亮下暗渐变 + 模糊 + 白边 + 顶部内高光 + 柔和阴影,跟边栏同一块玻璃。 */
.n-button.glass-btn {
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.85), rgba(255, 255, 255, 0.55));
  -webkit-backdrop-filter: saturate(180%) blur(16px);
  backdrop-filter: saturate(180%) blur(16px);
  border: 1px solid rgba(255, 255, 255, 0.9);
  border-radius: 999px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.10), inset 0 1px 0 rgba(255, 255, 255, 0.9);
  color: #007aff;
  padding: 0 16px;
}
.n-button.glass-btn:hover {
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.95), rgba(255, 255, 255, 0.7));
  color: #007aff;
}
</style>
