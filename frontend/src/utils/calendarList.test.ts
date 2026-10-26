import { describe, expect, it } from 'vitest'
import type { CalendarEvent } from '@/api/calendar'
import {
  eventDateText, groupEventsByMonth, monthLabel, monthsInRange, monthWeeks,
  resolveSemesterEnd, weekdayLabel,
} from '@/utils/calendarList'

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

describe('monthsInRange', () => {
  it('跨学年起止：2026-09 至 2027-01 共 5 个月', () => {
    expect(monthsInRange('2026-09-01', '2027-01-15').map((m) => m.label)).toEqual([
      '2026年9月', '2026年10月', '2026年11月', '2026年12月', '2027年1月',
    ])
  })
  it('起止在月中也各算整月', () => {
    expect(monthsInRange('2026-10-15', '2026-12-03').map((m) => m.label)).toEqual([
      '2026年10月', '2026年11月', '2026年12月',
    ])
  })
  it('起止颠倒返回空数组', () => {
    expect(monthsInRange('2026-12-01', '2026-10-01')).toEqual([])
  })
  it('同月起止只返回该月', () => {
    expect(monthsInRange('2026-10-05', '2026-10-20')).toEqual([
      { year: 2026, month: 10, label: '2026年10月' },
    ])
  })
})

describe('monthWeeks', () => {
  it('周一起头补齐格：2026年10月首格是 9月28日周一，10月1日在首行第 4 格', () => {
    const weeks = monthWeeks(2026, 10)
    expect(weeks[0]![0]).toEqual({ iso: '2026-09-28', dayNum: 28, inMonth: false })
    expect(weeks[0]![3]).toEqual({ iso: '2026-10-01', dayNum: 1, inMonth: true })
    expect(weeks.every((w) => w.length === 7)).toBe(true)
  })
  it('末格含结束日：2027年1月末格是 1月31日周日', () => {
    const weeks = monthWeeks(2027, 1)
    const last = weeks[weeks.length - 1]!
    expect(last[last.length - 1]).toEqual({ iso: '2027-01-31', dayNum: 31, inMonth: true })
  })
  it('2026年2月（28 天、2月1日是周日）首格是 1月26日周一', () => {
    const weeks = monthWeeks(2026, 2)
    expect(weeks[0]![0]).toEqual({ iso: '2026-01-26', dayNum: 26, inMonth: false })
    expect(weeks[0]![6]).toEqual({ iso: '2026-02-01', dayNum: 1, inMonth: true })
  })
})

describe('resolveSemesterEnd', () => {
  it('有结束日期就用它', () => {
    expect(resolveSemesterEnd('2026-09-01', '2027-01-15')).toBe('2027-01-15')
  })
  it('缺结束日期按开学起 20 周推算', () => {
    expect(resolveSemesterEnd('2026-09-01', null)).toBe('2027-01-19')
  })
  it('缺开始日期返回 null', () => {
    expect(resolveSemesterEnd(null, '2027-01-15')).toBe(null)
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
