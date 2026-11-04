import { describe, expect, it } from 'vitest'
import type { CalendarEvent } from '@/api/calendar'
import { autoMarkerKind, expandCalendarEvents, mondayOf, toISODate, weekdayOf } from './calendar'

function ev(partial: Partial<CalendarEvent>): CalendarEvent {
  return {
    id: 1, semester_id: 1, title: '活动', event_type: 'activity',
    scope_type: 'school', scope_id: null,
    start_date: '2026-10-19', end_date: '2026-10-19',
    period_start: null, period_end: null, weekly_recurring: false,
    note: null, created_by: null, created_at: '', updated_at: '',
    ...partial,
  }
}

describe('calendar utils', () => {
  it('mondayOf 回到周一,weekdayOf 周日为 7', () => {
    // 2026-10-25 是周日
    const sun = new Date(2026, 9, 25)
    expect(weekdayOf(sun)).toBe(7)
    expect(toISODate(mondayOf(sun))).toBe('2026-10-19')
    expect(toISODate(mondayOf(new Date(2026, 9, 19)))).toBe('2026-10-19')
  })

  it('一次性多日事件逐日展开并按区间裁剪', () => {
    const m = expandCalendarEvents(
      [ev({ start_date: '2026-10-20', end_date: '2026-10-22' })],
      '2026-10-21', '2026-10-25',
    )
    expect([...m.keys()].sort()).toEqual(['2026-10-21', '2026-10-22'])
  })

  it('每周重复事件只在同 weekday 展开,不早于 start 不晚于 end', () => {
    // 2026-10-19 是周一;重复到 11-09(周一)
    const m = expandCalendarEvents(
      [ev({ start_date: '2026-10-19', end_date: '2026-11-09', weekly_recurring: true })],
      '2026-10-12', '2026-11-15',
    )
    expect([...m.keys()].sort()).toEqual([
      '2026-10-19', '2026-10-26', '2026-11-02', '2026-11-09',
    ])
  })
})

describe('autoMarkerKind', () => {
  it('国家假日 / 调休 / 节日节气按备注区分,学校活动回 null', () => {
    expect(autoMarkerKind(ev({ note: '系统自动同步：公共假日' }))).toBe('national')
    expect(autoMarkerKind(ev({ note: '系统自动同步：调休上班' }))).toBe('workday')
    expect(autoMarkerKind(ev({ note: '系统自动同步：传统节日' }))).toBe('small')
    expect(autoMarkerKind(ev({ note: '系统自动同步：二十四节气' }))).toBe('small')
    expect(autoMarkerKind(ev({ note: null }))).toBe(null)
    expect(autoMarkerKind(ev({ note: '运动会备注' }))).toBe(null)
  })
})
