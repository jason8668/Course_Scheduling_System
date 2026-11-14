import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import PortalCalendarCard from './PortalCalendarCard.vue'
import type { CalendarEvent } from '@/api/calendar'

// 迷你校历卡:月网格、今天高亮、活动打点、翻月、完整校历链接、接口失败静默。
const TODAY = new Date()
const Y = TODAY.getFullYear()
const M = TODAY.getMonth() + 1
const pad = (n: number) => String(n).padStart(2, '0')
const iso = (d: number) => `${Y}-${pad(M)}-${pad(d)}`
const TODAY_ISO = iso(TODAY.getDate())
const MONTH_TITLE = `${Y}年${M}月`

function ev(partial: Partial<CalendarEvent> & { id: number }): CalendarEvent {
  return {
    semester_id: 1, title: '活动', event_type: 'activity', scope_type: 'school',
    scope_id: null, start_date: iso(15), end_date: iso(15),
    period_start: null, period_end: null, weekly_recurring: false,
    note: null, created_by: null, created_at: '', updated_at: '',
    ...partial,
  }
}

// 本月第一周的周一(用于每周重复事件的断言)
function firstMonday(): number {
  const first = new Date(Y, M - 1, 1)
  const dow = first.getDay() === 0 ? 7 : first.getDay()
  return 1 + (8 - dow) % 7
}

function fixture(): CalendarEvent[] {
  return [
    ev({ id: 1, title: '国庆节', event_type: 'holiday', start_date: iso(15), end_date: iso(15), note: '系统自动同步：公共假日' }),
    // 类型 other、但备注是国家假日档:红点走 autoMarkerKind 分支
    ev({ id: 2, title: '中秋节', event_type: 'other', start_date: iso(22), end_date: iso(22), note: '系统自动同步：公共假日' }),
    // 跨 3 天的活动:18/19/20 都应打蓝点
    ev({ id: 3, title: '运动会', event_type: 'activity', start_date: iso(18), end_date: iso(20) }),
    // 每周重复:每周一都打点
    ev({
      id: 4, title: '升旗', event_type: 'activity',
      start_date: iso(firstMonday()), end_date: iso(new Date(Y, M, 0).getDate()),
      weekly_recurring: true,
    }),
  ]
}

function json(data: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(data) })
}

function setupRouter() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'portal', component: { template: '<div />' } },
      { path: '/school-calendar', name: 'school-calendar', component: { template: '<div />' } },
    ],
  })
  return router
}

async function mountCard(semesterId: number | null = 1, fetchImpl?: (url: unknown) => unknown) {
  const router = setupRouter()
  await router.push('/')
  await router.isReady()
  if (fetchImpl) vi.stubGlobal('fetch', vi.fn(fetchImpl))
  const wrapper = mount(PortalCalendarCard, {
    props: { semesterId },
    global: { plugins: [router] },
  })
  await flushPromises()
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn((url: unknown) =>
    String(url).includes('/calendar-events') ? json(fixture()) : json({})))
})

describe('PortalCalendarCard', () => {
  it('月网格能渲染:表头日一二三四五六,标题是本月', async () => {
    const { wrapper } = await mountCard()
    const card = wrapper.find('[data-testid="portal-calendar"]')
    expect(card.exists()).toBe(true)
    expect(card.text()).toContain(MONTH_TITLE)
    expect(card.findAll('.cal-weekhead').map((w) => w.text()))
      .toEqual(['日', '一', '二', '三', '四', '五', '六'])
    // 一月 4~6 周 × 7 格
    expect(card.findAll('.cal-cell').length).toBeGreaterThanOrEqual(28)
  })

  it('今天高亮', async () => {
    const { wrapper } = await mountCard()
    const today = wrapper.find(`[data-iso="${TODAY_ISO}"]`)
    expect(today.exists()).toBe(true)
    expect(today.classes()).toContain('is-today')
  })

  it('接口返回活动时对应日期出现标记:放假红点、普通蓝点', async () => {
    const { wrapper } = await mountCard()
    // 15 日放假(holiday 类型)红点;22 日国家假日档(autoMarkerKind)红点
    for (const d of [15, 22]) {
      const dot = wrapper.find(`[data-iso="${iso(d)}"] .cal-dot`)
      expect(dot.exists()).toBe(true)
      expect(dot.classes()).toContain('dot-holiday')
    }
    // 18/19/20 跨天活动蓝点;每周一的升旗也打点
    for (const d of [18, 19, 20, firstMonday()]) {
      const dot = wrapper.find(`[data-iso="${iso(d)}"] .cal-dot`)
      expect(dot.exists()).toBe(true)
      expect(dot.classes()).not.toContain('dot-holiday')
    }
    // 无活动的日期不打点
    expect(wrapper.find(`[data-iso="${iso(10)}"] .cal-dot`).exists()).toBe(false)
  })

  it('翻月按钮切月', async () => {
    const { wrapper } = await mountCard()
    const prev = new Date(Y, M - 2, 1)
    const next = new Date(Y, M, 1)
    await wrapper.find('[data-testid="portal-calendar-prev"]').trigger('click')
    expect(wrapper.text()).toContain(`${prev.getFullYear()}年${prev.getMonth() + 1}月`)
    await wrapper.find('[data-testid="portal-calendar-next"]').trigger('click')
    await wrapper.find('[data-testid="portal-calendar-next"]').trigger('click')
    expect(wrapper.text()).toContain(`${next.getFullYear()}年${next.getMonth() + 1}月`)
  })

  it('完整校历链接指向 school-calendar', async () => {
    const { wrapper, router } = await mountCard()
    const link = wrapper.find('[data-testid="portal-calendar-full"]')
    expect(link.exists()).toBe(true)
    expect(link.text()).toContain('查看完整校历')
    await link.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('school-calendar')
  })

  it('接口失败时格子照常渲染,不编数据', async () => {
    const { wrapper } = await mountCard(1, () => Promise.reject(new Error('boom')))
    const card = wrapper.find('[data-testid="portal-calendar"]')
    expect(card.exists()).toBe(true)
    expect(card.text()).toContain(MONTH_TITLE)
    expect(card.findAll('.cal-cell').length).toBeGreaterThanOrEqual(28)
    expect(card.findAll('.cal-dot').length).toBe(0)
    expect(wrapper.find('[data-testid="portal-calendar-full"]').exists()).toBe(true)
  })

  it('semesterId 为 null 时只画格子、无标记,不调接口', async () => {
    const fetchFn = vi.fn(() => json([]))
    const { wrapper } = await mountCard(null, fetchFn)
    expect(fetchFn).not.toHaveBeenCalled()
    const card = wrapper.find('[data-testid="portal-calendar"]')
    expect(card.findAll('.cal-cell').length).toBeGreaterThanOrEqual(28)
    expect(card.findAll('.cal-dot').length).toBe(0)
  })
})
