import { flushPromises, mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import Substitutions from './Substitutions.vue'

// 调课的前端只做两件事:把后端算好的可对调节次列出来,点一下把「对调谁、哪一节、哪一天」送回去。
// 送错任何一个栏位,后端都会验到别的组合,所以这里把送出的内容钉死。

const affected = {
  id: 11, date: '2026-10-07', weekday: 3, period_no: 2, period_name: '第一节',
  start_time: null, end_time: null, subject_name: '国文', class_names: '701', room_name: '',
  status: 'pending', handler_teacher_id: null, handler_name: null, sub_type: null,
  swap_date: null, swap_period_name: '',
}
const leave = {
  id: 5, semester_id: 1, teacher_id: 1, teacher_name: '王师', leave_type: 'sick',
  leave_type_label: '病假', start_date: '2026-10-07', start_time: null, end_date: '2026-10-07',
  end_time: null, reason: '', status: 'registered', created_by_name: 'admin',
  created_at: '2026-10-01T08:00:00', affected_count: 1, pending_count: 1,
  affected_periods: [affected],
}
const swapOptions = {
  affected_period_id: 11, date_from: '2026-10-05', date_to: '2026-10-18',
  partners: [
    {
      teacher_id: 2, teacher_name: '陈师', teaches_same_class: true, blocked_reason: '',
      options: [{
        entry_id: 77, date: '2026-10-08', weekday: 4, period_no: 3, period_name: '第二节',
        class_names: '701', subject_name: '数学', same_class: true, in_block: false,
      }, {
        entry_id: 78, date: '2026-10-14', weekday: 3, period_no: 3, period_name: '第二节',
        class_names: '702', subject_name: '自然', same_class: false, in_block: true,
      }],
    },
    {
      teacher_id: 3, teacher_name: '林师', teaches_same_class: true,
      blocked_reason: '林师 2026-10-07 第一节 该时段有自己的课', options: [],
    },
  ],
}

const candidate = {
  teacher_id: 2, teacher_name: '陈师', same_subject: true, at_school_that_day: true,
  sub_periods_this_month: 0, reasons: ['同科'],
}

function stubFetch(leaveObj: unknown = leave, candidates: unknown[] = []) {
  const calls: { url: string; method: string; body?: unknown }[] = []
  vi.stubGlobal('fetch', vi.fn((url: string, init: RequestInit) => {
    calls.push({ url, method: init.method ?? 'GET', body: init.body && JSON.parse(String(init.body)) })
    let body: unknown = []
    if (url.includes('/swap-options')) body = swapOptions
    else if (url.includes('/recommendations')) {
      body = { affected_period_id: 11, candidates, no_candidate_hint: '无人可代' }
    } else if (url.includes('/substitution-funding-sources')) {
      body = ['公费代课', '自费代课', '课务自理', '不支课时']
    } else if (url.includes('/substitution-types')) body = { swap: '调课', substitute: '代课' }
    else if (url.includes('/semesters')) body = [{ id: 1, label: '115 学年度第 1 学期' }]
    else if (url.includes('/teachers')) body = []
    else if (url.includes('/leaves')) body = [leaveObj]
    else if (url.includes('/substitution')) body = { id: 1 }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) })
  }))
  return calls
}

async function openSwap() {
  const calls = stubFetch()
  const wrapper = mount({ render: () => h(NMessageProvider, () => h(Substitutions)) })
  await flushPromises()
  await wrapper.find('[data-testid="sub-handle"]').trigger('click')
  await flushPromises()
  await wrapper.find('[data-testid="sub-swap"]').trigger('click')
  await flushPromises()
  return { wrapper, calls }
}

// 代课单上要印「计费方式」,所以指派代课时一定要把它送出去;默认依假别(事假自费)
describe('调代课处理:代课的计费方式', () => {
  async function pick(leaveObj: unknown) {
    const calls = stubFetch(leaveObj, [candidate])
    const wrapper = mount({ render: () => h(NMessageProvider, () => h(Substitutions)) })
    await flushPromises()
    await wrapper.find('[data-testid="sub-handle"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-testid="sub-pick"]').trigger('click')
    await flushPromises()
    return calls.find((c) => c.method === 'PUT')
  }

  it('病假默认公费代课', async () => {
    expect((await pick(leave))?.body).toEqual({
      type: 'substitute', handler_teacher_id: 2, counts_toward_hours: true,
      funding_source: '公费代课',
    })
  })

  it('事假默认自费代课', async () => {
    const personal = { ...leave, leave_type: 'personal', leave_type_label: '事假' }
    expect((await pick(personal))?.body).toMatchObject({ funding_source: '自费代课' })
  })
})

describe('调代课处理:调课', () => {
  it('列出可对调节次,来不了的老师说明原因', async () => {
    const { wrapper } = await openSwap()
    const partners = wrapper.findAll('[data-testid="sub-swap-partner"]')
    expect(partners).toHaveLength(2)
    expect(partners[0].text()).toContain('10/8(周四) 第二节')
    expect(partners[1].text()).toContain('无法对调')
    expect(partners[1].text()).toContain('该时段有自己的课')
  })

  it('先只列同班节次,其他班收起来,展开后才出现', async () => {
    const { wrapper } = await openSwap()
    const first = () => wrapper.findAll('[data-testid="sub-swap-partner"]')[0]
    expect(first().findAll('[data-testid="sub-swap-option"]')).toHaveLength(1)
    expect(first().text()).toContain('显示其他班级的 1 个节次')

    await first().find('[data-testid="sub-swap-more"]').trigger('click')
    await flushPromises()
    const opts = first().findAll('[data-testid="sub-swap-option"]')
    expect(opts).toHaveLength(2)
    expect(opts[1].text()).toContain('连堂之一')
    expect(first().find('[data-testid="sub-swap-more"]').exists()).toBe(false)
  })

  it('默认找两周,放宽周数后重新查询', async () => {
    const { wrapper, calls } = await openSwap()
    const swapCalls = () => calls.filter((c) => c.url.includes('/swap-options'))
    expect(swapCalls()[0].url).toContain('weeks=2')

    const Swap = wrapper.findComponent(Substitutions)
    await (Swap.vm as unknown as { onSwapWeeksChange: (p: unknown, w: number) => Promise<void> })
      .onSwapWeeksChange({ id: 11 }, 4)
    await flushPromises()
    expect(swapCalls().at(-1)?.url).toContain('weeks=4')
  })

  it('点击节次送出调课:对调老师、那一节、补课日期', async () => {
    const { wrapper, calls } = await openSwap()
    await wrapper.find('[data-testid="sub-swap-option"]').trigger('click')
    await flushPromises()
    const put = calls.find((c) => c.method === 'PUT')
    expect(put?.url).toBe('/api/affected-periods/11/substitution')
    expect(put?.body).toEqual({
      type: 'swap', handler_teacher_id: 2, swap_entry_id: 77, swap_date: '2026-10-08',
      swap_period_no: 3,
    })
  })
})
