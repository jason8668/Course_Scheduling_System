import { flushPromises, mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import DingTalkImport from './DingTalkImport.vue'
import type { ClassUnit } from '@/api/basedata'

const CLASSES = [
  { id: 5, semester_id: 1, grade: 7, name: '1班', track: 'junior_high' },
  { id: 6, semester_id: 1, grade: 7, name: '2班', track: 'junior_high' },
] as unknown as ClassUnit[]

const DEPT_TREE = [
  {
    dept_id: 1, name: '校区一', parent_id: null,
    children: [{
      dept_id: 10, name: '初中', parent_id: 1,
      children: [{
        dept_id: 20, name: '七年级 2026级', parent_id: 10,
        children: [
          { dept_id: 40, name: '七年级 1班', parent_id: 20, children: [] },
          { dept_id: 41, name: '七年级 2班', parent_id: 20, children: [] },
        ],
      }],
    }],
  },
]

const PREVIEW = {
  dept_id: 40, dept_name: '七年级 1班',
  dept_path: ['校区一', '初中', '七年级 2026级', '七年级 1班'],
  total_members: 7, student_count: 4, guardian_count: 1, teacher_count: 1, unknown_count: 1,
  suggested_class_unit_id: 5, suggested_class_name: '1班',
  target_class_unit_id: 5, target_class_name: '1班',
  students: [
    { userid: 'U-s1', name: '张三', mobile: '13800000001', role: 'student',
      student_no: '20260101', student_no_missing: false, exists: 'update', missing_fields: [] },
    { userid: 'U-s2', name: '王小五', mobile: '', role: 'student',
      student_no: null, student_no_missing: true, exists: 'new', missing_fields: ['学号'] },
    { userid: 'U-s3', name: '李四', mobile: '13800000002', role: 'student',
      student_no: '20260999', student_no_missing: false, exists: 'same_name', missing_fields: [] },
    { userid: 'U-s4', name: '赵小六', mobile: '13800000003', role: 'student',
      student_no: '20260103', student_no_missing: false, exists: 'new', missing_fields: [] },
  ],
  unconfirmed: [{ userid: 'U-u1', name: '未知人', mobile: '', reason: '身份接口调用失败' }],
}

const IMPORT_RESULT = {
  created: 1, updated: 1, skipped: 2, errors: [],
  skipped_detail: ['「李四」同名同班的学生已存在,未新建', '「张父」在钉钉里的身份不是学生,未导入'],
}

// fetch 打桩:按 URL 分发夹具;deptMode 切到 'error' 时部门接口回 400(未配置)
let lastUrl = ''
let lastBody: unknown = null
let deptMode: 'ok' | 'error' = 'ok'
vi.stubGlobal('fetch', vi.fn((url: string, init: { method?: string; body?: string }) => {
  lastUrl = url
  lastBody = init.body ? JSON.parse(init.body) : null
  if (url === '/api/exam/students/dingtalk/departments') {
    if (deptMode === 'error') {
      return Promise.resolve({
        ok: false, status: 400,
        json: () => Promise.resolve({ detail: '钉钉应用未配置:请管理员在系统管理里填入钉钉应用的 appKey、应用密钥与 agentId。' }),
      })
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(DEPT_TREE) })
  }
  if (url === '/api/exam/students/dingtalk/preview') {
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(PREVIEW) })
  }
  if (url === '/api/exam/students/dingtalk/import') {
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(IMPORT_RESULT) })
  }
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
}))

// NModal 内容 teleport 到 body,文本与元素都在 document.body 里查
function bodyText(): string {
  return document.body.textContent ?? ''
}

function bodyEl(selector: string): HTMLElement | null {
  return document.body.querySelector(selector) as HTMLElement | null
}

async function mountImport() {
  deptMode = 'ok'
  const Host = {
    render: () => h(NMessageProvider, () => h(DingTalkImport, {
      semesterId: 1, classes: CLASSES,
    })),
  }
  const wrapper = mount(Host, { attachTo: document.body })
  await flushPromises()
  await flushPromises()
  return wrapper
}

async function selectClassDept() {
  const node = [...document.body.querySelectorAll('.n-tree-node-content')]
    .find((n) => n.textContent?.includes('七年级 1班')) as HTMLElement | undefined
  expect(node).toBeDefined()
  node!.click()
  await flushPromises()
  await flushPromises()
}

function fillStudentNo(value: string) {
  const input = bodyEl('input[placeholder="待补,填学号"]') as HTMLInputElement | null
  expect(input).not.toBeNull()
  input!.value = value
  input!.dispatchEvent(new Event('input', { bubbles: true }))
}

async function clickConfirm() {
  const btn = [...document.body.querySelectorAll('button')]
    .find((b) => b.textContent?.includes('确认导入')) as HTMLElement | undefined
  expect(btn).toBeDefined()
  btn!.click()
  await flushPromises()
  await flushPromises()
}

describe('从钉钉导入学生', () => {
  it('部门树渲染,选班级部门后拉预览:分角色计数、家长老师不在表里、同名与待补行标出', async () => {
    const w = await mountImport()
    try {
      expect(bodyText()).toContain('七年级 1班')
      await selectClassDept()
      expect(lastUrl).toBe('/api/exam/students/dingtalk/preview')
      expect(lastBody).toMatchObject({ semester_id: 1, dept_id: 40 })
      expect(bodyText()).toContain('学生 4 人')
      expect(bodyText()).toContain('家长 1 人')
      expect(bodyText()).toContain('老师 1 人')
      expect(bodyText()).toContain('张三')
      expect(bodyText()).toContain('赵小六')
      expect(bodyText()).toContain('王小五')
      expect(bodyText()).not.toContain('张父')
      expect(bodyText()).not.toContain('陈老师')
      expect(bodyText()).toContain('同名已存在')
      expect(bodyText()).toContain('未知人')
      expect(bodyText()).toContain('手机号仅供核对')
    } finally {
      w.unmount()
    }
  })

  it('学号待补的行填好前不可勾选(默认 2 人),填好学号后自动勾选', async () => {
    const w = await mountImport()
    try {
      await selectClassDept()
      expect(bodyText()).toContain('确认导入(2 人)')
      fillStudentNo('20260105')
      await flushPromises()
      expect(bodyText()).toContain('确认导入(3 人)')
    } finally {
      w.unmount()
    }
  })

  it('确认导入请求体只含勾选行且带补填学号,成功后显示新增/更新/跳过数', async () => {
    const w = await mountImport()
    try {
      await selectClassDept()
      fillStudentNo('20260105')
      await flushPromises()
      await clickConfirm()
      expect(lastUrl).toBe('/api/exam/students/dingtalk/import')
      expect(lastBody).toMatchObject({
        semester_id: 1, dept_id: 40, class_unit_id: 5,
        students: [
          { userid: 'U-s1', name: '张三', student_no: '20260101' },
          { userid: 'U-s2', name: '王小五', student_no: '20260105' },
          { userid: 'U-s4', name: '赵小六', student_no: '20260103' },
        ],
      })
      expect(bodyText()).toContain('新增 1 人,更新 1 人')
      expect(bodyText()).toContain('跳过 2 人')
    } finally {
      w.unmount()
    }
  })

  it('钉钉未配置时提示去系统管理填三件套', async () => {
    deptMode = 'error'
    const Host = {
      render: () => h(NMessageProvider, () => h(DingTalkImport, {
        semesterId: 1, classes: CLASSES,
      })),
    }
    const w = mount(Host, { attachTo: document.body })
    try {
      await flushPromises()
      await flushPromises()
      expect(bodyText()).toContain('钉钉应用未配置')
      expect(bodyText()).toContain('系统管理')
    } finally {
      w.unmount()
    }
  })
})
