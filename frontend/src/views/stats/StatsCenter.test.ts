import { flushPromises, mount } from '@vue/test-utils'
import naive from 'naive-ui'
import { describe, expect, it, vi } from 'vitest'
import StatsCenter from './StatsCenter.vue'

const SEMESTERS = [
  { id: 1, academic_year: 2026, term: 1, label: '2026-2027 学年 第 1 学期', status: 'active', start_date: '2026-09-01', end_date: '2027-01-31' },
]

function stubFetch() {
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    const body = url.includes('/semesters') ? SEMESTERS : []
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) })
  }))
}

function mountCenter() {
  return mount(StatsCenter, {
    global: {
      plugins: [naive],
      stubs: {
        StatsSubstituteCard: true,
        StatsTeachingCard: true,
        StatsNotifyCard: true,
      },
    },
  })
}

function cardProps(wrapper: ReturnType<typeof mountCenter>, name: string) {
  return wrapper.findComponent({ name }).props() as Record<string, unknown>
}

function fmt(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

async function pickScope(wrapper: ReturnType<typeof mountCenter>, testid: string) {
  // NRadioButton 渲染为 label 包 input;jsdom 里合成 click 不走 change 路径,
  // 直接置 checked 再触发 change,走 Naive 真正的更新 handler。
  const input = wrapper.find(`[data-testid="${testid}"] input`)
  ;(input.element as HTMLInputElement).checked = true
  await input.trigger('change')
  await flushPromises()
}

describe('StatsCenter', () => {
  it('默认本月范围,三块卡片收到当月起讫', async () => {
    stubFetch()
    const wrapper = mountCenter()
    await flushPromises()
    const now = new Date()
    const first = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-01`
    for (const name of ['StatsSubstituteCard', 'StatsTeachingCard', 'StatsNotifyCard']) {
      const props = cardProps(wrapper, name)
      expect(props.scope).toBe('month')
      expect(props.dateFrom).toBe(first)
      expect(props.dateTo).toBe(fmt(now))
    }
    expect(wrapper.find('[data-testid="scope-month"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="scope-semester"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="scope-custom"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="custom-range"]').exists()).toBe(false)
  })

  it('切到本学期,三块卡片收到学期起讫', async () => {
    stubFetch()
    const wrapper = mountCenter()
    await flushPromises()
    await pickScope(wrapper, 'scope-semester')
    for (const name of ['StatsSubstituteCard', 'StatsTeachingCard', 'StatsNotifyCard']) {
      const props = cardProps(wrapper, name)
      expect(props.scope).toBe('semester')
      expect(props.dateFrom).toBe('2026-09-01')
      expect(props.dateTo).toBe('2027-01-31')
    }
  })

  it('切到自定义,出现日期区间选择,未选前三块卡片收不到范围', async () => {
    stubFetch()
    const wrapper = mountCenter()
    await flushPromises()
    await pickScope(wrapper, 'scope-custom')
    expect(wrapper.find('[data-testid="custom-range"]').exists()).toBe(true)
    for (const name of ['StatsSubstituteCard', 'StatsTeachingCard', 'StatsNotifyCard']) {
      const props = cardProps(wrapper, name)
      expect(props.scope).toBe('custom')
      expect(props.dateFrom).toBeNull()
      expect(props.dateTo).toBeNull()
    }
  })
})
