// 校历相关的纯日期/展开工具(无副作用,可单测)。
// 全部以本地日期组 'YYYY-MM-DD',避免 toISOString 的 UTC 倒退问题。

import type { CalendarEvent } from '@/api/calendar'

/** Date → 'YYYY-MM-DD'(本地时区)。 */
export function toISODate(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/** 'YYYY-MM-DD' → 本地 Date(午夜)。 */
export function parseISODate(s: string): Date {
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, (m ?? 1) - 1, d ?? 1)
}

export function addDays(d: Date, n: number): Date {
  const out = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  out.setDate(out.getDate() + n)
  return out
}

/** JS getDay()(0=周日) → 课表 weekday(1=周一 … 7=周日)。 */
export function weekdayOf(d: Date): number {
  return d.getDay() === 0 ? 7 : d.getDay()
}

/** 含 d 那一周的周一(本地日期)。 */
export function mondayOf(d: Date): Date {
  return addDays(d, -(weekdayOf(d) - 1))
}

/**
 * 把校历事件展开到 [from, to] 区间内的每一天。
 * - 一次性事件:start_date..end_date 逐日展开(与区间取交集)。
 * - 每周重复事件:以 start_date 的 weekday 为准,在区间内每个同 weekday 的日期展开,
 *   且不早于 start_date、不晚于 end_date(重复事件的 end_date 即学期结束语义)。
 * 回传 Map<'YYYY-MM-DD', CalendarEvent[]>(同一天的事件保持输入顺序)。
 */
export function expandCalendarEvents(
  events: CalendarEvent[],
  from: string,
  to: string,
): Map<string, CalendarEvent[]> {
  const out = new Map<string, CalendarEvent[]>()
  const push = (iso: string, ev: CalendarEvent) => {
    out.set(iso, [...(out.get(iso) ?? []), ev])
  }
  for (const ev of events) {
    const start = ev.start_date < from ? from : ev.start_date
    const end = ev.end_date > to ? to : ev.end_date
    if (start > end) continue
    if (!ev.weekly_recurring) {
      for (let d = parseISODate(start); d <= parseISODate(end); d = addDays(d, 1)) {
        push(toISODate(d), ev)
      }
    } else {
      const targetWeekday = weekdayOf(parseISODate(ev.start_date))
      for (let d = parseISODate(start); d <= parseISODate(end); d = addDays(d, 1)) {
        if (weekdayOf(d) === targetWeekday) push(toISODate(d), ev)
      }
    }
  }
  return out
}

/** 事件在某一天是否覆盖某节次:全天(period 皆 null)覆盖所有节次。 */
export function eventCoversPeriod(
  ev: CalendarEvent,
  periodNo: number,
): boolean {
  if (ev.period_start === null || ev.period_end === null) return true
  return periodNo >= ev.period_start && periodNo <= ev.period_end
}
