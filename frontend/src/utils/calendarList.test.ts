import { describe, expect, it } from 'vitest'
import type { CalendarEvent } from '@/api/calendar'
import { eventDateText, groupEventsByMonth, monthLabel, weekdayLabel } from '@/utils/calendarList'

const base = (over: Partial<CalendarEvent>): CalendarEvent => ({
  id: 1,
  semester_id: 1,
  title: '活动',
  event_type: 'activity',
  scope_type: 'school',
  scope_id: null,
  start_date: '2026-10-30',
  end_date: '2026-10-30',
  period_start: null,
  period_end: null,
  weekly_recurring: false,
  note: null,
  created_by: null,
  created_at: '',
  updated_at: '',
  ...over,
})

describe('weekdayLabel / monthLabel', () => {
  it('2026-10-30 是周五,月份为 2026年10月', () => {
    expect(weekdayLabel('2026-10-30')).toBe('周五')
    expect(monthLabel('2026-10-30')).toBe('2026年10月')
  })
})

describe('eventDateText', () => {
  it('单日只写一日', () => {
    expect(eventDateText(base({}))).toBe('2026-10-30')
  })
  it('跨日写区间', () => {
    expect(eventDateText(base({ start_date: '2026-10-30', end_date: '2026-11-01' })))
      .toBe('2026-10-30 至 2026-11-01')
  })
  it('每周重复只显示一行,带每周星期与起止', () => {
    expect(eventDateText(base({ weekly_recurring: true, start_date: '2026-09-04', end_date: '2027-01-15' })))
      .toBe('每周五（2026-09-04 至 2027-01-15）')
  })
})

describe('groupEventsByMonth', () => {
  it('按开始日期月份分组、组内按日期排序', () => {
    const groups = groupEventsByMonth([
      base({ id: 3, start_date: '2026-11-02', end_date: '2026-11-02' }),
      base({ id: 1, start_date: '2026-10-30', end_date: '2026-10-30' }),
      base({ id: 2, start_date: '2026-10-05', end_date: '2026-10-05' }),
    ])
    expect(groups.map((g) => g.month)).toEqual(['2026年10月', '2026年11月'])
    expect(groups[0]!.events.map((e) => e.id)).toEqual([2, 1])
    expect(groups[1]!.events.map((e) => e.id)).toEqual([3])
  })
  it('每周重复事件归入开始日期月份', () => {
    const groups = groupEventsByMonth([
      base({ id: 9, weekly_recurring: true, start_date: '2026-09-04', end_date: '2027-01-15' }),
    ])
    expect(groups).toHaveLength(1)
    expect(groups[0]!.month).toBe('2026年9月')
  })
})
