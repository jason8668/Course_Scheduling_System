// 一页一览(主页面与打印页共用)的纯函数:日期文案与按月分组。
// 不碰 utils/calendar.ts 的公开签名,Dashboard 的本周课表不受影响。

import type { CalendarEvent } from '@/api/calendar'
import { parseISODate, weekdayOf } from '@/utils/calendar'

export const WEEKDAY_CN = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

/** 'YYYY-MM-DD' → '周X'。 */
export function weekdayLabel(iso: string): string {
  return WEEKDAY_CN[weekdayOf(parseISODate(iso)) - 1] ?? ''
}

/** 'YYYY-MM-DD' → '2026年10月'。 */
export function monthLabel(iso: string): string {
  const d = parseISODate(iso)
  return `${d.getFullYear()}年${d.getMonth() + 1}月`
}

/**
 * 日期列文案。
 * - 每周重复事件只显示一行(不展开成每周一条,避免一页被撑得很长):
 *   「每周X（开始日期 至 结束日期）」。
 * - 一次性事件:单日只写一日,跨日写区间。
 */
export function eventDateText(ev: CalendarEvent): string {
  if (ev.weekly_recurring) {
    return `每周${weekdayLabel(ev.start_date).slice(1)}（${ev.start_date} 至 ${ev.end_date}）`
  }
  return ev.start_date === ev.end_date
    ? ev.start_date
    : `${ev.start_date} 至 ${ev.end_date}`
}

export interface CalendarMonthGroup {
  month: string
  events: CalendarEvent[]
}

/**
 * 按开始日期月份分组,组内按开始日期、id 排序(后端已按此排序,此处再稳一次)。
 * 每周重复事件归入其开始日期所在的月份。
 */
export function groupEventsByMonth(events: CalendarEvent[]): CalendarMonthGroup[] {
  const sorted = [...events].sort((a, b) =>
    a.start_date === b.start_date ? a.id - b.id : a.start_date < b.start_date ? -1 : 1)
  const groups: CalendarMonthGroup[] = []
  for (const ev of sorted) {
    const month = monthLabel(ev.start_date)
    const last = groups[groups.length - 1]
    if (last && last.month === month) last.events.push(ev)
    else groups.push({ month, events: [ev] })
  }
  return groups
}
