import { flushPromises, mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { createPinia, setActivePinia } from 'pinia'
import { h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import ExamNumberRule from './ExamNumberRule.vue'
import { useAuthStore } from '@/stores/auth'

const S_SHAPE_WARNING = '暂无上次成绩，暂按学号顺序编排'

vi.stubGlobal('fetch', vi.fn((url: string, init: { method?: string }) => {
  if (url.startsWith('/api/semesters')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve([{ id: 1, academic_year: 2026, term: 1, label: '2026 学年第一学期', status: 'active', start_date: null, end_date: null }]),
    })
  }
  if (url.startsWith('/api/class-units')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve([
        { id: 5, semester_id: 1, grade: 7, name: '七年一班', track: 'junior_high', department: null, student_count: null, homeroom_teacher_id: null, homeroom_teacher: null, period_table_id: null },
      ]),
    })
  }
  if (url.startsWith('/api/exam/exam-number-rule/generate')) {
    expect(init.method).toBe('POST')
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({ generated: 12, warning: S_SHAPE_WARNING }),
    })
  }
  if (url.startsWith('/api/exam/exam-number-rule')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({ semester_id: 1, grade: 7, rule_type: 's_shape' }),
    })
  }
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
}))

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/exam/exam-number-rule', name: 'exam-number-rule', component: ExamNumberRule }],
  })
}

describe('考号规则页', () => {
  it('S 型生成后把后端警告原样展示出来', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    auth.user = {
      id: 1, username: 'admin', display_name: '系统管理员', roles: ['admin'],
      must_change_password: false,
    }
    const Host = { render: () => h(NMessageProvider, () => h(ExamNumberRule)) }
    const wrapper = mount(Host, { global: { plugins: [pinia, makeRouter()] } })
    await flushPromises()
    // 读到 S 型规则后,页面先提示无成绩时会暂按学号编排
    expect(wrapper.text()).toContain(S_SHAPE_WARNING)
    // 点一键生成,后端回的警告原样出现在结果区
    const buttons = wrapper.findAll('button')
    const gen = buttons.find((b) => b.text().includes('一键生成全年级考号'))
    expect(gen).toBeTruthy()
    await gen!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('已生成 12 人的考号')
    const warn = wrapper.find('[data-testid="exam-generate-warning"]')
    expect(warn.exists()).toBe(true)
    expect(warn.text()).toContain(S_SHAPE_WARNING)
  })
})
