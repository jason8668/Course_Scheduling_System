<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { listCalendarEvents } from '@/api/calendar'
import type { CalendarEvent } from '@/api/calendar'
import { autoMarkerKind, expandCalendarEvents, toISODate } from '@/utils/calendar'
import { monthWeeks } from '@/utils/calendarList'

// 迷你校历卡(总入口主页右上角):只看,不编数据;接口失败就只画格子,
// 格子和「查看完整校历」链接照常渲染。
const props = defineProps<{ semesterId: number | null }>()

const today = new Date()
const todayISO = toISODate(today)
const viewYear = ref(today.getFullYear())
const viewMonth = ref(today.getMonth() + 1) // 1-12
const events = ref<CalendarEvent[]>([])
const loadFailed = ref(false)

const monthTitle = computed(() => `${viewYear.value}年${viewMonth.value}月`)

// monthWeeks 是周一起头;迷你卡表头是日一二三四五六,每行把周日那格挪到最前,
// 只换列顺序,不重算月份格子。
const weeks = computed(() => monthWeeks(viewYear.value, viewMonth.value)
  .map((w) => [w[6]!, ...w.slice(0, 6)]))

const monthStart = computed(() =>
  `${viewYear.value}-${String(viewMonth.value).padStart(2, '0')}-01`)
const monthEnd = computed(() => toISODate(new Date(viewYear.value, viewMonth.value, 0)))
const expanded = computed(() =>
  expandCalendarEvents(events.value, monthStart.value, monthEnd.value))

function dayEvents(iso: string): CalendarEvent[] {
  return expanded.value.get(iso) ?? []
}
// 放假类:类型是 holiday,或自动同步的国家假日档——红点;其余活动蓝点。
function isHolidayDay(iso: string): boolean {
  return dayEvents(iso).some((ev) => ev.event_type === 'holiday' || autoMarkerKind(ev) === 'national')
}

function prevMonth() {
  if (viewMonth.value === 1) { viewYear.value -= 1; viewMonth.value = 12 }
  else viewMonth.value -= 1
}
function nextMonth() {
  if (viewMonth.value === 12) { viewYear.value += 1; viewMonth.value = 1 }
  else viewMonth.value += 1
}

async function load() {
  if (props.semesterId == null) {
    events.value = []
    loadFailed.value = false
    return
  }
  try {
    const data = await listCalendarEvents(props.semesterId)
    events.value = Array.isArray(data) ? data : []
    loadFailed.value = false
  } catch {
    // 静默缺失:格子和链接照常渲染,绝不编数据。
    events.value = []
    loadFailed.value = true
  }
}

watch(() => props.semesterId, () => { void load() }, { immediate: true })
</script>

<template>
  <div class="cal-card" data-testid="portal-calendar">
    <div class="cal-head">
      <button type="button" class="cal-nav" data-testid="portal-calendar-prev" aria-label="上个月" @click="prevMonth">‹</button>
      <span class="cal-title">{{ monthTitle }}</span>
      <button type="button" class="cal-nav" data-testid="portal-calendar-next" aria-label="下个月" @click="nextMonth">›</button>
    </div>
    <div class="cal-weekheads">
      <span v-for="h in ['日', '一', '二', '三', '四', '五', '六']" :key="h" class="cal-weekhead">{{ h }}</span>
    </div>
    <div v-for="(week, wi) in weeks" :key="wi" class="cal-week">
      <div
        v-for="cell in week" :key="cell.iso"
        class="cal-cell"
        :class="{ 'is-today': cell.iso === todayISO, 'is-out': !cell.inMonth }"
        :data-iso="cell.iso"
      >
        <span class="cal-daynum">{{ cell.dayNum }}</span>
        <span
          v-if="dayEvents(cell.iso).length" class="cal-dot"
          :class="{ 'dot-holiday': isHolidayDay(cell.iso) }"
        />
      </div>
    </div>
    <div class="cal-foot">
      <router-link data-testid="portal-calendar-full" :to="{ name: 'school-calendar' }">查看完整校历 →</router-link>
    </div>
  </div>
</template>

<style scoped>
/* 走 Portal 的蓝:卡片 #DCE9FD、内格 #EAF3FE,与总入口其它卡同色。 */
.cal-card {
  background: #dce9fd;
  border: 1px solid rgba(0, 122, 255, 0.16);
  border-radius: 20px;
  box-shadow: 0 6px 20px rgba(0, 122, 255, 0.1);
  padding: 14px 16px;
}
.cal-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.cal-title { font-size: 15px; font-weight: 700; color: #1d1d1f; }
.cal-nav {
  width: 28px; height: 28px; border-radius: 50%; border: 1px solid rgba(0, 122, 255, 0.18);
  background: #eaf3fe; color: #007aff; font-size: 18px; line-height: 1; cursor: pointer;
}
.cal-weekheads, .cal-week { display: grid; grid-template-columns: repeat(7, 1fr); gap: 2px; }
.cal-week { margin-bottom: 2px; }
.cal-weekhead { text-align: center; font-size: 12px; color: #5b7ba6; padding: 2px 0; }
.cal-cell {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  min-height: 34px; border-radius: 8px; background: #eaf3fe;
}
.cal-cell.is-out { opacity: 0.45; }
.cal-daynum {
  display: inline-flex; align-items: center; justify-content: center;
  width: 22px; height: 22px; font-size: 13px; color: #1d1d1f;
}
.cal-cell.is-today .cal-daynum { background: #007aff; color: #fff; border-radius: 50%; font-weight: 700; }
.cal-dot { width: 5px; height: 5px; border-radius: 50%; background: #007aff; margin-top: 1px; }
.cal-dot.dot-holiday { background: #c0392b; }
.cal-foot { margin-top: 10px; text-align: right; font-size: 13px; }
.cal-foot a { color: #007aff; text-decoration: none; }
</style>
