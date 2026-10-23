import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import SubstitutionLog from './SubstitutionLog.vue'

// 后端取到上限笔数就代表「还有更早的没列出来」。不讲的话,组长会以为这学期就只有这些纪录。
const MAX_ROWS = 1000

const entry = (id: number) => ({
  affected_period_id: id, date: '2026-09-02', weekday: 3, period_no: 1, period_name: '第一节',
  start_time: null, end_time: null, class_names: '701', subject_name: '国文', room_name: '',
  absent_teacher_id: 1, absent_teacher_name: '王师', leave_type: 'sick', leave_type_label: '病假',
  status: 'pending', status_label: '待处理', disposed: false, sub_type: null, sub_type_label: null,
  handler_teacher_id: null, handler_name: null, counts_toward_hours: null, swap_date: null,
  swap_period_name: '', swap_class_names: '', swap_subject_name: '', note: '', row_kind: 'leave',
})

function stubFetch(rows: number) {
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    let body: unknown = Array.from({ length: rows }, (_, i) => entry(i + 1))
    if (url.includes('/leave-types')) body = { sick: '病假' }
    else if (url.includes('/teachers')) body = []
    else if (url.includes('/semesters')) body = [{ id: 1, label: '149 学年度第 1 学期' }]
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) })
  }))
}

async function mountLog(rows: number) {
  stubFetch(rows)
  const wrapper = mount(SubstitutionLog)
  await flushPromises()
  return wrapper
}

describe('SubstitutionLog 查询上限', () => {
  it('取到上限笔数时提示被截断,并告诉用户怎么看到更早的', async () => {
    const wrapper = await mountLog(MAX_ROWS)
    expect(wrapper.find('[data-testid="log-truncated"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('只显示最新的 1000 笔')
    expect(wrapper.text()).toContain('缩小日期区间')
  })

  it('未达上限时不提示(否则每次查询都在喊狼来了)', async () => {
    const wrapper = await mountLog(3)
    expect(wrapper.find('[data-testid="log-truncated"]').exists()).toBe(false)
  })
})
