import { flushPromises, mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { createPinia, setActivePinia } from 'pinia'
import { h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import ExamArrangement from './ExamArrangement.vue'
import { useAuthStore } from '@/stores/auth'

let lockedState = false

function stubFetch() {
  vi.stubGlobal('fetch', vi.fn((url: string, init?: { method?: string }) => {
    const method = init?.method ?? 'GET'
    if (url === '/api/exam/exams/3/arrange' && method === 'POST') {
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve({
          assigned: 1, rooms_used: 1, warnings: ['暂无上次成绩，暂按学号顺序编排'],
        }),
      })
    }
    if (url.startsWith('/api/exam/exams/3/rooms')) {
      return Promise.resolve({
        ok: true, status: 200, json: () => Promise.resolve({ items: [], total: 0 }),
      })
    }
    if (url.startsWith('/api/exam/exams/3/arrangement-rule')) {
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve({
          exam_id: 3, mode: 's_shape', scatter_same_class: true, max_per_room: 30,
        }),
      })
    }
    if (url.startsWith('/api/exam/exams/3/arrangement-lock')) {
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve({ locked: lockedState, locked_by: '教务', locked_at: '2026-11-14' }),
      })
    }
    if (url.startsWith('/api/exam/exams/3/arrangements')) {
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve({
          items: [{
            id: 11, exam_id: 3, subject_id: 2, subject_name: '数学', room_id: 12,
            room_name: '201', student_id: 9, student_no: '202601', student_name: '张三',
            class_name: '七年一班', seat_no: 1, special_note: null,
          }],
          total: 1,
        }),
      })
    }
    if (url.startsWith('/api/exam/exams/3/seat-map')) {
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve({
          rooms: [{
            room_id: 12, room_name: '201',
            seats: [{
              seat_no: 1, student_no: '202601', student_name: '张三',
              class_name: '七年一班', special_note: null,
            }],
          }],
        }),
      })
    }
    if (url.startsWith('/api/exam/exams/3')) {
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve({
          id: 3, semester_id: 1, name: '期中考试', exam_type: '期中', grades: [7],
          status: '草稿', description: null, created_at: '2026-11-01',
          subjects: [{
            subject_id: 2, subject_name: '数学', exam_date: '2026-11-20',
            start_time: '08:00', end_time: '10:00', full_score: 120,
          }],
          participant_count: 0,
        }),
      })
    }
    if (url.startsWith('/api/rooms')) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) })
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
  }))
}

async function makeRouter() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/exam/exams/:id', name: 'exam-exam-detail', component: { template: '<div />' } },
      { path: '/exam/exams/:id/arrange', name: 'exam-exam-arrange', component: ExamArrangement },
    ],
  })
  await router.push('/exam/exams/3/arrange')
  await router.isReady()
  return router
}

async function mountPage(locked: boolean) {
  lockedState = locked
  stubFetch()
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.user = {
    id: 1, username: 'admin', display_name: '系统管理员', roles: ['admin'],
    must_change_password: false,
  }
  const Host = { render: () => h(NMessageProvider, () => h(ExamArrangement)) }
  const wrapper = mount(Host, { global: { plugins: [pinia, await makeRouter()] } })
  await flushPromises()
  await flushPromises()
  return wrapper
}

function isDisabled(wrapper: VueWrapper, testid: string): boolean {
  const el = wrapper.find(`[data-testid="${testid}"]`).element as HTMLButtonElement
  return el.disabled === true
}

describe('考场编排页(KW-15~22)', () => {
  it('座位表按考场分组展示考生', async () => {
    const wrapper = await mountPage(false)
    expect(wrapper.text()).toContain('期中考试')
    expect(wrapper.text()).toContain('201')
    expect(wrapper.text()).toContain('张三')
    expect(wrapper.text()).toContain('202601')
  })

  it('一键编排后 warnings 原样展示,不改写 S 型无成绩警告', async () => {
    const wrapper = await mountPage(false)
    const run = wrapper.find('[data-testid="arrange-run"]')
    expect(isDisabled(wrapper, 'arrange-run')).toBe(false)
    await run.trigger('click')
    await flushPromises()
    await flushPromises()
    const box = wrapper.find('[data-testid="arrange-warnings"]')
    expect(box.exists()).toBe(true)
    expect(box.text()).toContain('暂无上次成绩，暂按学号顺序编排')
    expect(wrapper.find('[data-testid="arrange-result"]').text()).toContain('已编排 1 人')
  })

  it('锁定态:编排与手动调整按钮置灰,并提示“已锁定，请先解锁”', async () => {
    const wrapper = await mountPage(true)
    expect(wrapper.find('[data-testid="arrangement-locked-hint"]').text())
      .toContain('已锁定，请先解锁')
    expect(isDisabled(wrapper, 'arrange-run')).toBe(true)
    expect(isDisabled(wrapper, 'arrange-add-room')).toBe(true)
    expect(isDisabled(wrapper, 'arrange-save-rule')).toBe(true)
    expect(isDisabled(wrapper, 'arrange-move')).toBe(true)
    expect(isDisabled(wrapper, 'arrange-swap')).toBe(true)
    // 导出与查看不受锁定影响:导出按钮仍可用
    expect(isDisabled(wrapper, 'arrange-export')).toBe(false)
  })

  it('未锁定态:编排按钮可用,无锁定提示', async () => {
    const wrapper = await mountPage(false)
    expect(wrapper.find('[data-testid="arrangement-locked-hint"]').exists()).toBe(false)
    expect(isDisabled(wrapper, 'arrange-run')).toBe(false)
    expect(isDisabled(wrapper, 'arrange-add-room')).toBe(false)
  })
})
