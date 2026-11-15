import { flushPromises, mount } from '@vue/test-utils'
import { NMessageProvider, NSelect } from 'naive-ui'
import { createPinia, setActivePinia } from 'pinia'
import { h } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import ExamAdmissionTickets from './ExamAdmissionTickets.vue'
import { useAuthStore } from '@/stores/auth'
import {
  filterTicketsByClass, listAdmissionTickets, sortTicketSubjects, ticketClassNames,
} from '@/api/exam'
import type { AdmissionTicket } from '@/api/exam'

const EXAM = {
  id: 3, semester_id: 1, name: '期中考试', exam_type: '期中', grades: [7],
  status: '草稿', description: null, created_at: '2026-11-01',
  subjects: [{
    subject_id: 2, subject_name: '数学', exam_date: '2026-11-20',
    start_time: '08:00', end_time: '10:00', full_score: 120,
  }],
  participant_count: 2,
}

const TICKETS: AdmissionTicket[] = [
  {
    student_id: 9, student_no: '202601', exam_no: '2026001', student_name: '张三',
    class_name: '七年一班', grade: 7,
    subjects: [{
      subject_id: 2, subject_name: '数学', exam_date: '2026-11-20',
      start_time: '08:00', end_time: '10:00', room_name: '201', seat_no: 1,
    }],
  },
  {
    student_id: 10, student_no: '202602', exam_no: '2026002', student_name: '李四',
    class_name: '七年二班', grade: 7,
    subjects: [{
      subject_id: 2, subject_name: '数学', exam_date: '2026-11-20',
      start_time: '08:00', end_time: '10:00', room_name: '202', seat_no: 2,
    }],
  },
]

let lastFetchUrl = ''

function stubFetch() {
  lastFetchUrl = ''
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    lastFetchUrl = url
    if (url.startsWith('/api/exam/exams/3/admission-tickets')) {
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve({ items: TICKETS, total: 2 }),
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
      { path: '/exam/exams/:id/admission-tickets', name: 'exam-exam-admission-tickets', component: ExamAdmissionTickets },
    ],
  })
  await router.push('/exam/exams/3/admission-tickets')
  await router.isReady()
  const Host = { render: () => h(NMessageProvider, () => h(ExamAdmissionTickets)) }
  const wrapper = mount(Host, { global: { plugins: [pinia, router] } })
  await flushPromises()
  await flushPromises()
  return wrapper
}

afterEach(() => { vi.unstubAllGlobals() })

describe('准考证客户端(KW-19)', () => {
  it('请求路径与参数:带班级与考场参数拼成查询串', async () => {
    stubFetch()
    await listAdmissionTickets(3, { classUnitId: 5, roomId: 7 })
    expect(lastFetchUrl).toBe('/api/exam/exams/3/admission-tickets?class_unit_id=5&room_id=7')
  })

  it('请求路径与参数:无参数时不带查询串', async () => {
    stubFetch()
    await listAdmissionTickets(3)
    expect(lastFetchUrl).toBe('/api/exam/exams/3/admission-tickets')
  })
})

describe('准考证按班级筛选逻辑(KW-19)', () => {
  it('ticketClassNames 取出不重复的班级名并排序', () => {
    expect(ticketClassNames([...TICKETS, TICKETS[0]])).toEqual(['七年一班', '七年二班'])
  })

  it('filterTicketsByClass:空筛选返回全部,指定班级只留该班', () => {
    expect(filterTicketsByClass(TICKETS, null)).toHaveLength(2)
    const one = filterTicketsByClass(TICKETS, '七年二班')
    expect(one).toHaveLength(1)
    expect(one[0].student_name).toBe('李四')
  })

  it('sortTicketSubjects 按考试日期与开始时间排序', () => {
    const sorted = sortTicketSubjects([
      { subject_id: 3, subject_name: '英语', exam_date: '2026-11-21', start_time: '08:00', end_time: '10:00', room_name: '201', seat_no: 1 },
      { subject_id: 2, subject_name: '数学', exam_date: '2026-11-20', start_time: '10:30', end_time: '12:00', room_name: '201', seat_no: 1 },
      { subject_id: 4, subject_name: '语文', exam_date: '2026-11-20', start_time: '08:00', end_time: '10:00', room_name: '201', seat_no: 1 },
    ])
    expect(sorted.map((s) => s.subject_name)).toEqual(['语文', '数学', '英语'])
  })

  it('页面按班级筛选后只显示该班准考证', async () => {
    const wrapper = await mountPage()
    expect(wrapper.text()).toContain('张三')
    expect(wrapper.text()).toContain('李四')
    const sel = wrapper.findComponent(NSelect)
    expect(sel.exists()).toBe(true)
    ;(sel.vm as unknown as { $emit: (e: string, v: string) => void })
      .$emit('update:value', '七年二班')
    await flushPromises()
    expect(wrapper.text()).toContain('李四')
    expect(wrapper.text()).not.toContain('张三')
  })

  it('准考证含姓名、考号、考场、座位号与各科日程', async () => {
    const wrapper = await mountPage()
    expect(wrapper.text()).toContain('准考证')
    expect(wrapper.text()).toContain('2026001')
    expect(wrapper.text()).toContain('201')
    expect(wrapper.text()).toContain('数学')
    expect(wrapper.text()).toContain('2026-11-20')
  })
})
