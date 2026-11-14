import { flushPromises, mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { createPinia, setActivePinia } from 'pinia'
import { h } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import ExamAttendanceSheets from './ExamAttendanceSheets.vue'
import { useAuthStore } from '@/stores/auth'
import { groupAttendanceByRoomSubject } from '@/api/exam'
import type { ArrangementItem } from '@/api/exam'

const EXAM = {
  id: 3, semester_id: 1, name: '期中考试', exam_type: '期中', grades: [7],
  status: '草稿', description: null, created_at: '2026-11-01',
  subjects: [
    { subject_id: 2, subject_name: '数学', exam_date: '2026-11-20', start_time: '08:00', end_time: '10:00', full_score: 120 },
    { subject_id: 3, subject_name: '语文', exam_date: '2026-11-20', start_time: '10:30', end_time: '12:00', full_score: 120 },
  ],
  participant_count: 3,
}

function item(partial: Partial<ArrangementItem> & { id: number }): ArrangementItem {
  return {
    exam_id: 3, subject_id: 2, subject_name: '数学', room_id: 12, room_name: '201',
    student_id: 9, student_no: '202601', student_name: '张三', class_name: '七年一班',
    seat_no: 1, special_note: null, exam_no: '2026001', ...partial,
  }
}

const ITEMS: ArrangementItem[] = [
  item({ id: 11, seat_no: 2, student_name: '李四', student_no: '202602', exam_no: '2026002' }),
  item({ id: 12, seat_no: 1, student_name: '张三', student_no: '202601', exam_no: '2026001' }),
  item({ id: 13, subject_id: 3, subject_name: '语文', seat_no: 1, student_name: '王五', student_no: '202603', exam_no: null }),
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
      { path: '/exam/exams/:id/attendance-sheets', name: 'exam-exam-attendance-sheets', component: ExamAttendanceSheets },
    ],
  })
  await router.push('/exam/exams/3/attendance-sheets')
  await router.isReady()
  const Host = { render: () => h(NMessageProvider, () => h(ExamAttendanceSheets)) }
  const wrapper = mount(Host, { global: { plugins: [pinia, router] } })
  await flushPromises()
  await flushPromises()
  return wrapper
}

afterEach(() => { vi.unstubAllGlobals() })

describe('考场名单与签到表分组逻辑(KW-20)', () => {
  it('按考场 + 科目分组,组内按座位号排序', () => {
    const groups = groupAttendanceByRoomSubject(ITEMS)
    expect(groups).toHaveLength(2)
    const math = groups.find((g) => g.subject_name === '数学')!
    expect(math.items.map((a) => a.student_name)).toEqual(['张三', '李四'])
    const chinese = groups.find((g) => g.subject_name === '语文')!
    expect(chinese.items).toHaveLength(1)
  })

  it('空编排结果返回空分组,不崩', () => {
    expect(groupAttendanceByRoomSubject([])).toEqual([])
  })
})

describe('考场名单与签到表打印页(KW-20)', () => {
  it('每组出表:含序号、考号、姓名、班级、座位号与签到栏', async () => {
    const wrapper = await mountPage()
    expect(wrapper.text()).toContain('考场名单与签到表')
    expect(wrapper.text()).toContain('201')
    expect(wrapper.text()).toContain('数学')
    expect(wrapper.text()).toContain('语文')
    expect(wrapper.text()).toContain('张三')
    expect(wrapper.text()).toContain('2026001')
    expect(wrapper.text()).toContain('签到')
    expect(wrapper.text()).toContain('缺考')
  })

  it('考号为空的考生显示—,不崩', async () => {
    const wrapper = await mountPage()
    expect(wrapper.text()).toContain('王五')
    // 王五的考号为空,表格该格显示 —
    expect(wrapper.text()).toContain('—')
  })
})
