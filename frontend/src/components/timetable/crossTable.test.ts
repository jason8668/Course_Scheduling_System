import { describe, expect, it } from 'vitest'
import { crossTableNote, extraRows } from './crossTable'

// 初中小:初中(默认,45 分)与小学(40 分)两套节次表
const junior = {
  id: 1, is_default: true,
  periods: [
    { weekday: 1, period_no: 2, start_time: '08:20:00', end_time: '09:05:00' },
    { weekday: 1, period_no: 3, start_time: '09:15:00', end_time: '10:00:00' },
  ],
}
const elementary = {
  id: 2, is_default: false,
  periods: [
    { weekday: 1, period_no: 2, start_time: '08:30:00', end_time: '09:10:00' },
    { weekday: 1, period_no: 3, start_time: '09:15:00', end_time: '10:00:00' },
  ],
}
const classes = [{ id: 10, period_table_id: null }, { id: 20, period_table_id: 2 }]
const tables = [junior, elementary]

describe('crossTableNote', () => {
  it('另一套节次表、时间不同 → 标出实际时间', () => {
    expect(crossTableNote({ weekday: 1, period_no: 2, class_ids: [20] }, classes, tables, junior))
      .toBe('08:30–09:10')
  })
  it('另一套节次表但那一节时间刚好相同 → 不标', () => {
    expect(crossTableNote({ weekday: 1, period_no: 3, class_ids: [20] }, classes, tables, junior))
      .toBeUndefined()
  })
  it('同一套节次表(含没指定、走默认表的班级)→ 不标', () => {
    expect(crossTableNote({ weekday: 1, period_no: 2, class_ids: [10] }, classes, tables, junior))
      .toBeUndefined()
  })
  it('只有一套节次表的学校完全不受影响', () => {
    expect(crossTableNote({ weekday: 1, period_no: 2, class_ids: [10] }, classes, [junior], junior))
      .toBeUndefined()
  })
})

// 完全中学:初中(默认)没有第八节,高中部有
const senior = {
  id: 3, is_default: false,
  periods: [
    { weekday: 1, period_no: 2, start_time: '08:10:00', end_time: '09:00:00' },
    { weekday: 1, period_no: 10, start_time: '16:20:00', end_time: '17:10:00' },
    { weekday: 2, period_no: 10, start_time: '16:20:00', end_time: '17:10:00' },
  ],
}
const k12Classes = [{ id: 10, period_table_id: null }, { id: 30, period_table_id: 3 }]
const k12Tables = [junior, senior]

describe('extraRows', () => {
  it('界面那套没有的节次(高中第八节)→ 补上整列,课才不会从教师课表消失', () => {
    const rows = extraRows(
      [{ weekday: 1, period_no: 10, class_ids: [30] }], k12Classes, k12Tables, junior)
    expect(rows.map((p) => [p.weekday, p.period_no])).toEqual([[1, 10], [2, 10]])
  })
  it('界面那套本来就有的节次不重复补', () => {
    expect(extraRows(
      [{ weekday: 1, period_no: 2, class_ids: [30] }], k12Classes, k12Tables, junior)).toEqual([])
  })
  it('没有跨部的老师不会多出空列', () => {
    expect(extraRows(
      [{ weekday: 1, period_no: 2, class_ids: [10] }], k12Classes, k12Tables, junior)).toEqual([])
  })
  it('只补用得到的那一列一次(两堂课都在第八节)', () => {
    const rows = extraRows([
      { weekday: 1, period_no: 10, class_ids: [30] }, { weekday: 2, period_no: 10, class_ids: [30] },
    ], k12Classes, k12Tables, junior)
    expect(rows).toHaveLength(2)
  })
})
