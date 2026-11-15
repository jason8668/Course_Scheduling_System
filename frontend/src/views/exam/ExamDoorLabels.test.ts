import { flushPromises, mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { createPinia, setActivePinia } from 'pinia'
import { h } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import ExamDoorLabels from './ExamDoorLabels.vue'
import { useAuthStore } from '@/stores/auth'
import { compareExamNo, examNoRange } from '@/api/exam'
import type { ArrangementItem } from '@/api/exam'

const EXAM = {
  id: 3, semester_id: 1, name: '期中考试', exam_type: '期中', grades: [7],
  status: '草稿', description: null, created_at: '2026-11-01',
  subjects: [{
    subject_id: 2, subject_name: '数学', exam_date: '2026-11-20',
    start_time: '08:00', end_time: '10:00', full_score: 120,
  }],
  participant_count: 3,
}

function item(partial: Partial<ArrangementItem> & { id: number }): ArrangementItem {
  return {
    exam_id: 3, subject_id: 2, subject_name: '数学', room_id: 12, room_name: '201',
    student_id: 9, student_no: '202601', student_name: '张三', class_name: '七年一班', grade: 7,
    seat_no: 1, special_note: null, exam_no: '2026001', ...partial,
  }
}

const ITEMS: ArrangementItem[] = [
  item({ id: 11, seat_no: 1, exam_no: '2026001', student_name: '张三' }),
  item({ id: 12, seat_no: 2, exam_no: '2026003', student_name: '李四' }),
  item({ id: 13, seat_no: 3, exam_no: '2026002', student_name: '王五' }),
]

function stubFetch() {
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    if (url.startsWith('/api/exam/exams/3/arrangements')) {
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve({ items: ITEMS, total: 3 }),
      })
    }
    if (url.startsWith('/api/exam/exams/3')) {
      return Promise.resolve({
        ok: true, status: 200, json: () => Promise.resolve(EXAM),
      })
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
  }))
}

async function mountPage() {
  stubFetch()
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.user = {
    id: 1, username: 'admin', display_name: '系统管理员', roles: ['admin'],
    must_change_password: false,
  }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/exam/exams/:id/arrange', name: 'exam-exam-arrange', component: { template: '<div />' } },
      { path: '/exam/exams/:id/door-labels', name: 'exam-exam-door-labels', component: ExamDoorLabels },
    ],
  })
  await router.push('/exam/exams/3/door-labels')
  await router.isReady()
  const Host = { render: () => h(NMessageProvider, () => h(ExamDoorLabels)) }
  const wrapper = mount(Host, { global: { plugins: [pinia, router] } })
  await flushPromises()
  await flushPromises()
  return wrapper
}

afterEach(() => { vi.unstubAllGlobals() })

describe('门贴起止号计算逻辑(KW-21)', () => {
  it('数字考号按数值取起止,与输入顺序无关', () => {
    expect(examNoRange(['2026003', '2026001', '2026002'])).toEqual({
      start: '2026001', end: '2026003',
    })
  })

  it('不同位数的数字考号按数值比,不按字符串比', () => {
    // 字符串比会把 20260010 排在 2026002 前面,数值比不会
    expect(examNoRange(['2026002', '20260010'])).toEqual({
      start: '2026002', end: '20260010',
    })
    expect(compareExamNo('2026002', '20260010')).toBeLessThan(0)
  })

  it('空、null、空白考号被忽略,全空返回 null', () => {
    expect(examNoRange(['2026001', null, '', '  ', undefined])).toEqual({
      start: '2026001', end: '2026001',
    })
    expect(examNoRange([null, '', undefined])).toBeNull()
    expect(examNoRange([])).toBeNull()
  })

  it('单个考号起止相同', () => {
    expect(examNoRange(['2026005'])).toEqual({ start: '2026005', end: '2026005' })
  })
})

describe('考场门贴与桌贴打印页(KW-21)', () => {
  it('门贴每考场一张:考场号、考生起止号、人数', async () => {
    const wrapper = await mountPage()
    expect(wrapper.text()).toContain('考场门贴与桌贴')
    const door = wrapper.find('[data-testid="door-label"]')
    expect(door.exists()).toBe(true)
    expect(door.text()).toContain('201')
    expect(door.text()).toContain('2026001')
    expect(door.text()).toContain('2026003')
    expect(door.text()).toContain('共 3 人')
  })

  it('桌贴每座位一张:考号、姓名', async () => {
    const wrapper = await mountPage()
    const desks = wrapper.findAll('[data-testid="desk-label"]')
    expect(desks).toHaveLength(3)
    expect(wrapper.text()).toContain('李四')
    expect(wrapper.text()).toContain('2026002')
  })

  it('页面顶部注明桌贴是否使用请学校确认', async () => {
    const wrapper = await mountPage()
    expect(wrapper.text()).toContain('是否使用桌贴请学校确认')
  })
})
