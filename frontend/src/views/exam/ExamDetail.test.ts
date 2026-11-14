import { flushPromises, mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import { NButton, NMessageProvider, NSelect } from 'naive-ui'
import { createPinia, setActivePinia } from 'pinia'
import { h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import ExamDetail from './ExamDetail.vue'
import { useAuthStore } from '@/stores/auth'

interface Fixtures {
  subjects?: { id: number; name: string }[]
  classes?: { id: number; name: string; grade: number }[]
  students?: { id: number; name: string; student_no: string; class_name: string }[]
  participants?: { id: number; student_name: string; class_name: string }[]
}

// 记录每一次 fetch(方法 + URL + body),批量用例断言请求走对了端点与参数。
const seenRequests: { url: string; method: string; body: unknown }[] = []

function stubFetchFor(status: string, fixtures: Fixtures = {}) {
  seenRequests.length = 0
  vi.stubGlobal('fetch', vi.fn((url: string, init: { method?: string; body?: string } = {}) => {
    seenRequests.push({
      url,
      method: init.method ?? 'GET',
      body: init.body ? JSON.parse(init.body) : null,
    })
    if (url.startsWith('/api/exam/exams/3/participants/bulk')) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ created: 2, skipped: 1 }) })
    }
    if (url.startsWith('/api/exam/exams/3/participants')) {
      const items = fixtures.participants ?? []
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ items, total: items.length }) })
    }
    if (url.startsWith('/api/exam/exams/3/paper-info')) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ items: [] }) })
    }
    if (url.startsWith('/api/exam/exams/3/special-arrangements')) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ items: [] }) })
    }
    if (url.startsWith('/api/exam/exams/3')) {
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve({
          id: 3, semester_id: 1, name: '期中考试', exam_type: '期中', grades: [7],
          status, description: null, created_at: '2026-11-01', subjects: [], participant_count: 0,
        }),
      })
    }
    if (url.startsWith('/api/exam/students')) {
      const items = fixtures.students ?? []
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ items, total: items.length }) })
    }
    if (url.startsWith('/api/subjects')) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(fixtures.subjects ?? []) })
    }
    if (url.startsWith('/api/class-units')) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(fixtures.classes ?? []) })
    }
    if (url.startsWith('/api/teachers')) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) })
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
  }))
}

async function makeRouter() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/exam/exams', name: 'exam-exams', component: { template: '<div />' } },
      { path: '/exam/exams/:id', name: 'exam-exam-detail', component: ExamDetail },
    ],
  })
  await router.push('/exam/exams/3')
  await router.isReady()
  return router
}

async function mountDetail(status: string, fixtures: Fixtures = {}) {
  stubFetchFor(status, fixtures)
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.user = {
    id: 1, username: 'admin', display_name: '系统管理员', roles: ['admin'],
    must_change_password: false,
  }
  const Host = { render: () => h(NMessageProvider, () => h(ExamDetail)) }
  const wrapper = mount(Host, { global: { plugins: [pinia, await makeRouter()] } })
  await flushPromises()
  await flushPromises()
  return wrapper
}

describe('考试详情页状态流转', () => {
  it('草稿状态:当前状态高亮,推进按钮指向已发布,回退按钮可见', async () => {
    const wrapper = await mountDetail('草稿')
    expect(wrapper.text()).toContain('期中考试')
    const current = wrapper.find('[data-testid="exam-current-status"]')
    expect(current.exists()).toBe(true)
    expect(current.text()).toBe('草稿')
    const advance = wrapper.find('[data-testid="exam-advance"]')
    expect(advance.exists()).toBe(true)
    expect(advance.text()).toContain('推进到已发布')
    expect(wrapper.find('[data-testid="exam-backward"]').exists()).toBe(false)
  })

  it('进行中状态:推进按钮指向成绩处理中,回退按钮可见', async () => {
    const wrapper = await mountDetail('进行中')
    const advance = wrapper.find('[data-testid="exam-advance"]')
    expect(advance.exists()).toBe(true)
    expect(advance.text()).toContain('推进到成绩处理中')
    expect(wrapper.find('[data-testid="exam-backward"]').exists()).toBe(true)
  })

  it('已归档状态:没有推进按钮,显示流转结束', async () => {
    const wrapper = await mountDetail('已归档')
    expect(wrapper.find('[data-testid="exam-advance"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('已归档,状态流转已结束')
  })

  it('特殊考生安排区有仅教务与监考可见的隐私提示', async () => {
    const wrapper = await mountDetail('草稿')
    const tip = wrapper.find('[data-testid="special-arrangement-privacy"]')
    expect(tip.exists()).toBe(true)
    expect(tip.text()).toContain('仅教务与相关监考教师可见')
  })
})

describe('考试日程与参试名单批量添加', () => {
  const fixtures: Fixtures = {
    subjects: [
      { id: 1, name: '语文' },
      { id: 2, name: '数学' },
      { id: 3, name: '英语' },
    ],
    classes: [
      { id: 5, name: '701', grade: 7 },
      { id: 6, name: '801', grade: 8 },
    ],
    students: [
      { id: 11, name: '张三', student_no: '20260101', class_name: '701' },
      { id: 12, name: '李四', student_no: '20260102', class_name: '701' },
      { id: 13, name: '王五', student_no: '20260201', class_name: '801' },
    ],
    participants: [
      { id: 1, student_name: '张三', class_name: '701' },
      { id: 2, student_name: '李四', class_name: '701' },
      { id: 3, student_name: '王五', class_name: '801' },
    ],
  }

  // 按 placeholder 找下拉(仓库里已有用 $emit('update:value') 驱动 n-select 的模式)。
  function findSelect(wrapper: VueWrapper, placeholder: string) {
    const sel = wrapper.findAllComponents(NSelect)
      .find((c) => c.props('placeholder') === placeholder)
    expect(sel?.exists()).toBe(true)
    return sel as NonNullable<typeof sel>
  }
  function emitSelectValue(
    sel: ReturnType<typeof findSelect>, value: number[],
  ) {
    ;(sel.vm as unknown as { $emit: (e: string, v: number[]) => void })
      .$emit('update:value', value)
  }
  function findButton(wrapper: VueWrapper, text: string) {
    const btn = wrapper.findAllComponents(NButton)
      .find((b) => b.text().trim() === text)
    expect(btn?.exists()).toBe(true)
    return btn as NonNullable<typeof btn>
  }

  it('日程:一次勾选两个科目,点一次添加科目,两科一起进日程表', async () => {
    const wrapper = await mountDetail('草稿', fixtures)
    emitSelectValue(findSelect(wrapper, '选择科目(可多选)'), [1, 2])
    await findButton(wrapper, '添加科目').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('语文')
    expect(wrapper.text()).toContain('数学')
    expect(wrapper.text()).not.toContain('英语')
  })

  it('日程:点全选再添加,三个科目一次全进日程表', async () => {
    const wrapper = await mountDetail('草稿', fixtures)
    await findButton(wrapper, '全选').trigger('click')
    await findButton(wrapper, '添加科目').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('语文')
    expect(wrapper.text()).toContain('数学')
    expect(wrapper.text()).toContain('英语')
  })

  it('参试名单:一次勾选两个班级,请求带两个 class_unit_ids', async () => {
    const wrapper = await mountDetail('草稿', fixtures)
    emitSelectValue(findSelect(wrapper, '班级(可多选)'), [5, 6])
    await flushPromises()
    await flushPromises()
    const hit = seenRequests.find((r) =>
      r.url.includes('class_unit_ids=5') && r.url.includes('class_unit_ids=6'))
    expect(hit).toBeDefined()
  })

  it('个别增补:一次勾选两名学生,点一次增补走批量端点', async () => {
    const wrapper = await mountDetail('草稿', fixtures)
    await findButton(wrapper, '个别增补').trigger('click')
    await flushPromises()
    emitSelectValue(findSelect(wrapper, '按姓名或学号选择学生(可多选)'), [11, 12])
    await findButton(wrapper, '增补').trigger('click')
    await flushPromises()
    await flushPromises()
    const hit = seenRequests.find((r) =>
      r.url === '/api/exam/exams/3/participants/bulk' && r.method === 'POST')
    expect(hit).toBeDefined()
    expect(hit?.body).toMatchObject({ student_ids: [11, 12] })
  })
})
