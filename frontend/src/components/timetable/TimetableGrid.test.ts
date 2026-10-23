import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import TimetableGrid from './TimetableGrid.vue'
import type { GridEntry, PeriodCell } from './types'

// 3 天 × 3 节:第2节为午休(反灰),周三第3节为固定用途(反灰),其余一般课
const periods: PeriodCell[] = []
for (let w = 1; w <= 3; w++) {
  periods.push({ weekday: w, period_no: 1, name: '第一节', type: 'regular', start_time: '08:00:00', end_time: '08:40:00' })
  periods.push({ weekday: w, period_no: 2, name: '午休', type: 'lunch' })
  periods.push({ weekday: w, period_no: 3, name: w === 3 ? '周三不排' : '第三节', type: w === 3 ? 'reserved' : 'regular' })
}
const entries: GridEntry[] = [
  { id: 1, weekday: 1, period_no: 1, subject: '国文', teacher: '王师', locked: true },
  { id: 2, weekday: 2, period_no: 1, subject: '数学', teacher: '李师' },
]

const DT = { getData: () => '', setData: () => {}, effectAllowed: '' }

function cell(wrapper: ReturnType<typeof mount>, w: number, p: number) {
  return wrapper.find(`[data-weekday="${w}"][data-period="${p}"]`)
}

describe('TimetableGrid', () => {
  it('渲染星期表头、节次名称与反灰不排课时段', () => {
    const w = mount(TimetableGrid, { props: { periods, entries } })
    expect(w.text()).toContain('星期一')
    expect(w.text()).toContain('星期三')
    expect(w.text()).toContain('第一节')
    // 午休与周三不排为反灰
    expect(cell(w, 1, 2).classes()).toContain('is-blocked')
    expect(cell(w, 3, 3).classes()).toContain('is-blocked')
    expect(cell(w, 1, 2).text()).toContain('午休')
  })

  it('渲染格位卡片;锁定卡显示锁图示且不可拖曳', () => {
    const w = mount(TimetableGrid, { props: { periods, entries } })
    const locked = cell(w, 1, 1)
    expect(locked.text()).toContain('国文')
    expect(locked.text()).toContain('王师')
    expect(locked.find('.tg-lock').exists()).toBe(true)
    expect(locked.find('.tg-card').attributes('draggable')).toBe('false')
    // 未锁定卡可拖曳
    expect(cell(w, 2, 1).find('.tg-card').attributes('draggable')).toBe('true')
  })

  it('格位有补充说明(跨节次表的实际时间)时显示在卡片上;没有就不占位置', () => {
    const noted: GridEntry[] = [...entries, { id: 3, weekday: 3, period_no: 1, subject: '英语', teacher: '601', note: '08:30–09:10' }]
    const w = mount(TimetableGrid, { props: { periods, entries: noted } })
    expect(cell(w, 3, 1).find('[data-testid="tg-note"]').text()).toBe('08:30–09:10')
    expect(cell(w, 1, 1).find('[data-testid="tg-note"]').exists()).toBe(false)
  })

  it('点击卡片触发 select', async () => {
    const w = mount(TimetableGrid, { props: { periods, entries } })
    await cell(w, 2, 1).find('.tg-card').trigger('click')
    expect(w.emitted('select')?.[0]?.[0]).toMatchObject({ id: 2 })
  })

  it('拖曳未锁定卡片触发 dragstart', async () => {
    const w = mount(TimetableGrid, { props: { periods, entries } })
    await cell(w, 2, 1).find('.tg-card').trigger('dragstart', { dataTransfer: { ...DT } })
    expect(w.emitted('dragstart')?.[0]?.[0]).toMatchObject({ source: 'grid', entryId: 2 })
  })

  it('拖入空的一般课格触发 check,放下触发 drop(带目标与 dragging 内容)', async () => {
    const dragging = { source: 'tray' as const, assignmentId: 9 }
    const w = mount(TimetableGrid, { props: { periods, entries, dragging } })
    await cell(w, 1, 3).trigger('dragenter', { dataTransfer: { ...DT } })
    expect(w.emitted('check')?.[0]?.[0]).toMatchObject({ weekday: 1, period_no: 3 })
    await cell(w, 1, 3).trigger('drop', { dataTransfer: { ...DT } })
    expect(w.emitted('drop')?.[0]?.[0]).toMatchObject({
      weekday: 1, period_no: 3, data: { source: 'tray', assignmentId: 9 },
    })
  })

  it('反灰时段不接受放下(不触发 drop)', async () => {
    const w = mount(TimetableGrid, { props: { periods, entries, dragging: { source: 'tray', assignmentId: 9 } } })
    await cell(w, 1, 2).trigger('drop', { dataTransfer: { ...DT } }) // 午休
    expect(w.emitted('drop')).toBeUndefined()
  })

  it('feedback 冲突时套用红框样式并显示原因', () => {
    const w = mount(TimetableGrid, {
      props: { periods, entries, feedback: { weekday: 1, period_no: 3, ok: false, reason: '王师此时段已有课' } },
    })
    const c = cell(w, 1, 3)
    expect(c.classes()).toContain('is-conflict')
    expect(c.text()).toContain('王师此时段已有课')
  })

  it('readonly 模式下格位不可放下', async () => {
    const w = mount(TimetableGrid, {
      props: { periods, entries, readonly: true, dragging: { source: 'tray', assignmentId: 9 } },
    })
    await cell(w, 1, 3).trigger('drop', { dataTransfer: { ...DT } })
    expect(w.emitted('drop')).toBeUndefined()
  })
  it('单双周的格子:单周、双周两堂上下并列,单周在上', () => {
    const alt: GridEntry[] = [
      { id: 11, weekday: 2, period_no: 3, subject: '资科', teacher: '乙师', week: '双' },
      { id: 10, weekday: 2, period_no: 3, subject: '生科', teacher: '甲师', week: '单' },
    ]
    const w = mount(TimetableGrid, { props: { periods, entries: alt } })
    const lines = cell(w, 2, 3).findAll('[data-testid="tg-week"]')
    expect(lines).toHaveLength(2)
    expect(lines[0].text()).toBe('单生科甲师')
    expect(lines[1].text()).toBe('双资科乙师')
  })
})
