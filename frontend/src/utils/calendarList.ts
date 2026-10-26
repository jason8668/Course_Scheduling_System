// 一页一览(主页面与打印页共用)的纯函数:日期文案与按月分组。
// 不碰 utils/calendar.ts 的公开签名,Dashboard 的本周课表不受影响。

import type { CalendarEvent } from '@/api/calendar'
import { addDays, mondayOf, parseISODate, toISODate, weekdayOf } from '@/utils/calendar'

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

export interface CalendarMonth {
  year: number
  month: number // 1-12
  label: string // 如「2026年10月」
}

/**
 * 覆盖 [startIso, endIso] 的月份列表（起止在月中也各算整月）。
 * 起止颠倒时返回空数组。
 */
export function monthsInRange(startIso: string, endIso: string): CalendarMonth[] {
  if (startIso > endIso) return []
  const start = parseISODate(startIso)
  const end = parseISODate(endIso)
  const out: CalendarMonth[] = []
  let y = start.getFullYear()
  let m = start.getMonth() + 1
  const endY = end.getFullYear()
  const endM = end.getMonth() + 1
  while (y < endY || (y === endY && m <= endM)) {
    out.push({ year: y, month: m, label: `${y}年${m}月` })
    m += 1
    if (m > 12) { m = 1; y += 1 }
  }
  return out
}

export interface MonthCell {
  iso: string
  dayNum: number
  inMonth: boolean
}

/**
 * 某月的日历网格：周一起头，每行 7 格；首尾用上月/下月日期补齐。
 * 返回按周分组的格子（每格含 iso、日期数字、本月标记）。
 */
export function monthWeeks(year: number, month: number): MonthCell[][] {
  const first = new Date(year, month - 1, 1)
  const last = new Date(year, month, 0)
  const weeks: MonthCell[][] = []
  let cursor = mondayOf(first)
  while (cursor <= last) {
    const week: MonthCell[] = []
    for (let i = 0; i < 7; i++) {
      const d = addDays(cursor, i)
      week.push({
        iso: toISODate(d),
        dayNum: d.getDate(),
        inMonth: d.getMonth() === month - 1,
      })
    }
    weeks.push(week)
    cursor = addDays(cursor, 7)
  }
  return weeks
}

/**
 * 学期结束日期：有 end_date 就用它；缺失时按开学起 20 周（约一学期）推算。
 * start 缺失时返回 null（调用方据此显示“补开始日期”提示，不画凑数的月份）。
 */
export function resolveSemesterEnd(startIso: string | null, endIso: string | null): string | null {
  if (!startIso) return null
  if (endIso) return endIso
  return toISODate(addDays(parseISODate(startIso), 20 * 7))
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
