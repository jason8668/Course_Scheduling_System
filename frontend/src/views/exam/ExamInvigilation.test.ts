import { flushPromises, mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import { NButton, NMessageProvider, NSelect } from 'naive-ui'
import { createPinia, setActivePinia } from 'pinia'
import { h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import ExamInvigilation from './ExamInvigilation.vue'
import {
  DEFAULT_INVIGILATION_RULE, DISCIPLINE_TYPES, INVIGILATION_ROLE, SHEET_VIEW_LABELS,
  addInvigilations, createDiscipline, createInvigilation, createPatrol, deleteDiscipline, deleteInvigilation,
  deletePatrol, exportInvigilationWorkload, getInvigilationRule, getInvigilationSheet,
  getInvigilationWorkload, getRoomSheet, getTeacherSheet, invigilateExam, listDiscipline,
  listInvigilations, listInvigilators, listPatrols, normalizeSheetView, saveInvigilationRule,
  saveInvigilators, toggleSheetView, updateDiscipline, updateInvigilation, updatePatrol,
} from '@/api/exam'
import { useAuthStore } from '@/stores/auth'

// fetch 打桩:记下最后一次请求的 URL、方法与 body,按端点回固定 JSON
let lastUrl = ''
let lastMethod = ''
let lastBody: unknown = null
// 批量监考请求的 body 记录:确认添加后还会跑三次重载,lastBody 会被覆盖,单独记批量请求。
const bulkHits: unknown[] = []
// jsdom 里 a.click() 会触发导航报错:下载链接点击在此处是无操作桩
vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
vi.stubGlobal('URL', {
  createObjectURL: () => 'blob:fake',
  revokeObjectURL: () => {},
})

const EXAM_JSON = {
  id: 3, semester_id: 1, name: '期中考试', exam_type: '期中', grades: [7],
  status: '草稿', description: null, created_at: '2026-11-01',
  subjects: [{
    subject_id: 2, subject_name: '数学', exam_date: '2026-11-20',
    start_time: '08:00', end_time: '10:00', full_score: 120,
  }],
  participant_count: 0,
}

vi.stubGlobal('fetch', vi.fn((url: string, init?: { method?: string; body?: string }) => {
  lastUrl = url
  lastMethod = init?.method ?? 'GET'
  lastBody = init?.body ? JSON.parse(init.body) : null
  const ok = (json: unknown) => Promise.resolve({
    ok: true, status: 200, headers: { get: () => null },
    blob: () => Promise.resolve(new Blob(['x'])),
    json: () => Promise.resolve(json),
  })
  if (url === '/api/exam/exams/3/invigilate' && lastMethod === 'POST') {
    return ok({
      assigned: 4,
      warnings: ['王老师与课表冲突，未排入数学场', '201 考场人选不足，未排满 2 人'],
    })
  }
  if (url.startsWith('/api/exam/exams/3/invigilation-rule')) {
    return ok({
      exam_id: 3, avoid_own_class: true, avoid_own_subject: true, invigilators_per_room: 2,
    })
  }
  if (url.startsWith('/api/exam/exams/3/invigilators')) {
    return ok({
      items: [
        { teacher_id: 1, teacher_name: '王老师', eligible: true },
        { teacher_id: 2, teacher_name: '李老师', eligible: false },
      ],
      total: 2,
    })
  }
  if (url === '/api/exam/exams/3/invigilations/bulk' && lastMethod === 'POST') {
    bulkHits.push(lastBody)
    return ok({ created: 2, skipped: 0 })
  }
  if (url.startsWith('/api/exam/exams/3/invigilations/')) {
    if (lastMethod === 'DELETE') {
      return Promise.resolve({ ok: true, status: 204, json: () => Promise.resolve(undefined) })
    }
    return ok({
      id: 5, exam_id: 3, subject_id: 2, subject_name: '数学', room_id: 12,
      room_name: '201', teacher_id: 9, teacher_name: '赵老师', role: '监考',
    })
  }
  if (url.startsWith('/api/exam/exams/3/invigilations')) {
    if (lastMethod === 'POST') {
      return ok({
        id: 5, exam_id: 3, subject_id: 2, subject_name: '数学', room_id: 12,
        room_name: '201', teacher_id: 1, teacher_name: '王老师', role: '监考',
      })
    }
    return ok({
      items: [{
        id: 5, exam_id: 3, subject_id: 2, subject_name: '数学', room_id: 12,
        room_name: '201', teacher_id: 1, teacher_name: '王老师', role: '监考',
      }],
      total: 1,
    })
  }
  if (url.startsWith('/api/exam/exams/3/invigilation-sheets')) {
    if (url.includes('view=room')) {
      return ok({
        rooms: [{
          room_id: 12, room_name: '201 考场',
          sessions: [{
            subject_name: '数学', exam_date: '2026-11-20',
            start_time: '08:00', end_time: '10:00', teachers: ['李老师'],
          }],
        }],
      })
    }
    return ok({
      teachers: [{
        teacher_id: 1, teacher_name: '王老师',
        sessions: [{
          subject_name: '数学', exam_date: '2026-11-20',
          start_time: '08:00', end_time: '10:00', room_name: '201',
        }],
      }],
    })
  }
  if (url.startsWith('/api/exam/exams/3/patrols/')) {
    if (lastMethod === 'DELETE') {
      return Promise.resolve({ ok: true, status: 204, json: () => Promise.resolve(undefined) })
    }
    return ok({
      id: 7, exam_id: 3, exam_date: '2026-11-20', teacher_id: 1,
      teacher_name: '王老师', scope: '二楼 201-206 考场', note: null,
    })
  }
  if (url.startsWith('/api/exam/exams/3/patrols')) {
    if (lastMethod === 'POST') {
      return ok({
        id: 7, exam_id: 3, exam_date: '2026-11-20', teacher_id: 1,
        teacher_name: '王老师', scope: '二楼 201-206 考场', note: null,
      })
    }
    return ok({ items: [], total: 0 })
  }
  if (url.startsWith('/api/exam/exams/3/invigilation-workload/export')) {
    return ok(null)
  }
  if (url.startsWith('/api/exam/exams/3/invigilation-workload')) {
    return ok({
      items: [{ teacher_id: 1, teacher_name: '王老师', sessions: 2, minutes: 240 }],
      total: 1,
    })
  }
  if (url.startsWith('/api/exam/exams/3/discipline/')) {
    if (lastMethod === 'DELETE') {
      return Promise.resolve({ ok: true, status: 204, json: () => Promise.resolve(undefined) })
    }
    return ok({
      id: 9, exam_id: 3, subject_id: 2, subject_name: '数学', student_id: 4,
      student_no: '202601', student_name: '张三', class_name: '七年一班',
      type: '作弊', description: '考试中查看手机', handling: '取消该科成绩',
      recorded_by: 1, recorded_by_name: 'admin', created_at: '2026-11-14',
    })
  }
  if (url.startsWith('/api/exam/exams/3/discipline')) {
    if (lastMethod === 'POST') {
      return ok({
        id: 9, exam_id: 3, subject_id: 2, subject_name: '数学', student_id: 4,
        student_no: '202601', student_name: '张三', class_name: '七年一班',
        type: '作弊', description: '考试中查看手机', handling: '取消该科成绩',
        recorded_by: 1, recorded_by_name: 'admin', created_at: '2026-11-14',
      })
    }
    return ok({ items: [], total: 0 })
  }
  if (url.startsWith('/api/exam/exams/3/rooms')) {
    return ok({
      items: [{
        id: 1, exam_id: 3, room_id: 12, room_name: '201',
        capacity: 30, room_type: 'normal', is_special: false,
      }],
      total: 1,
    })
  }
  if (url.startsWith('/api/exam/exams/3')) {
    return ok(EXAM_JSON)
  }
  if (url.startsWith('/api/teachers')) {
    return ok([{ id: 1, semester_id: 1, name: '王老师', base_periods: 0, admin_title: null, admin_reduction: 0, is_external: false, is_active: true, subjects: [], email: null, phone: null, user_id: null, grade_ids: [], is_grade_director: false }])
  }
  if (url.startsWith('/api/exam/students')) {
    return ok({ items: [], total: 0 })
  }
  return ok({})
}))

describe('监考安排 API 客户端(KW-23~29)', () => {
  it('监考规则查询与保存走 /invigilation-rule,默认两项回避都开、每考场 2 人', async () => {
    expect(DEFAULT_INVIGILATION_RULE).toEqual({
      avoid_own_class: true, avoid_own_subject: true, invigilators_per_room: 2,
    })
    await getInvigilationRule(3)
    expect(lastUrl).toBe('/api/exam/exams/3/invigilation-rule')
    expect(lastMethod).toBe('GET')
    await saveInvigilationRule(3, { avoid_own_class: false, avoid_own_subject: true, invigilators_per_room: 3 })
    expect(lastUrl).toBe('/api/exam/exams/3/invigilation-rule')
    expect(lastMethod).toBe('PUT')
    expect(lastBody).toMatchObject({ avoid_own_class: false, avoid_own_subject: true, invigilators_per_room: 3 })
  })

  it('教师池查询与保存走 /invigilators,保存只发 teacher_id 与 eligible', async () => {
    await listInvigilators(3)
    expect(lastUrl).toBe('/api/exam/exams/3/invigilators')
    expect(lastMethod).toBe('GET')
    await saveInvigilators(3, [{ teacher_id: 1, eligible: true }, { teacher_id: 2, eligible: false }])
    expect(lastUrl).toBe('/api/exam/exams/3/invigilators')
    expect(lastMethod).toBe('PUT')
    expect(lastBody).toEqual({
      items: [{ teacher_id: 1, eligible: true }, { teacher_id: 2, eligible: false }],
    })
  })

  it('自动排监考走 POST /invigilate:不选科目发空对象,选科目带 subject_id', async () => {
    await invigilateExam(3)
    expect(lastUrl).toBe('/api/exam/exams/3/invigilate')
    expect(lastMethod).toBe('POST')
    expect(lastBody).toEqual({})
    await invigilateExam(3, 2)
    expect(lastBody).toMatchObject({ subject_id: 2 })
    const res = await invigilateExam(3, 2)
    expect(res.assigned).toBe(4)
    expect(res.warnings).toEqual(['王老师与课表冲突，未排入数学场', '201 考场人选不足，未排满 2 人'])
  })

  it('监考安排查询、新增、替补换人与删除走契约端点', async () => {
    await listInvigilations(3, { subjectId: 2, roomId: 12, teacherId: 1 })
    expect(lastUrl).toBe('/api/exam/exams/3/invigilations?subject_id=2&room_id=12&teacher_id=1')
    expect(lastMethod).toBe('GET')
    await listInvigilations(3)
    expect(lastUrl).toBe('/api/exam/exams/3/invigilations')
    await createInvigilation(3, { subject_id: 2, room_id: 12, teacher_id: 1, role: '监考' })
    expect(lastUrl).toBe('/api/exam/exams/3/invigilations')
    expect(lastMethod).toBe('POST')
    expect(lastBody).toMatchObject({ subject_id: 2, room_id: 12, teacher_id: 1, role: '监考' })
    await updateInvigilation(3, 5, { teacher_id: 9 })
    expect(lastUrl).toBe('/api/exam/exams/3/invigilations/5')
    expect(lastMethod).toBe('PATCH')
    expect(lastBody).toMatchObject({ teacher_id: 9 })
    await deleteInvigilation(3, 5)
    expect(lastUrl).toBe('/api/exam/exams/3/invigilations/5')
    expect(lastMethod).toBe('DELETE')
  })

  it('批量手工安排监考走 POST /invigilations/bulk:同一科目同一考场多位教师', async () => {
    const res = await addInvigilations(3, { subject_id: 2, room_id: 12, teacher_ids: [1, 2], role: '监考' })
    expect(lastUrl).toBe('/api/exam/exams/3/invigilations/bulk')
    expect(lastMethod).toBe('POST')
    expect(lastBody).toMatchObject({ subject_id: 2, room_id: 12, teacher_ids: [1, 2], role: '监考' })
    expect(res).toEqual({ created: 2, skipped: 0 })
  })

  it('巡考安排增删改查走 /patrols', async () => {
    await listPatrols(3)
    expect(lastUrl).toBe('/api/exam/exams/3/patrols')
    expect(lastMethod).toBe('GET')
    await createPatrol(3, { exam_date: '2026-11-20', teacher_id: 1, scope: '二楼 201-206 考场' })
    expect(lastUrl).toBe('/api/exam/exams/3/patrols')
    expect(lastMethod).toBe('POST')
    expect(lastBody).toMatchObject({ exam_date: '2026-11-20', teacher_id: 1, scope: '二楼 201-206 考场' })
    await updatePatrol(3, 7, { scope: '三楼考场' })
    expect(lastUrl).toBe('/api/exam/exams/3/patrols/7')
    expect(lastMethod).toBe('PATCH')
    expect(lastBody).toMatchObject({ scope: '三楼考场' })
    await deletePatrol(3, 7)
    expect(lastUrl).toBe('/api/exam/exams/3/patrols/7')
    expect(lastMethod).toBe('DELETE')
  })

  it('监考表两视图走 /invigilation-sheets?view=teacher|room,可按科目筛选', async () => {
    await getTeacherSheet(3)
    expect(lastUrl).toBe('/api/exam/exams/3/invigilation-sheets?view=teacher')
    await getTeacherSheet(3, 2)
    expect(lastUrl).toBe('/api/exam/exams/3/invigilation-sheets?view=teacher&subject_id=2')
    await getRoomSheet(3)
    expect(lastUrl).toBe('/api/exam/exams/3/invigilation-sheets?view=room')
    await getInvigilationSheet(3, 'room', 2)
    expect(lastUrl).toBe('/api/exam/exams/3/invigilation-sheets?view=room&subject_id=2')
    await getInvigilationSheet(3, 'teacher')
    expect(lastUrl).toBe('/api/exam/exams/3/invigilation-sheets?view=teacher')
  })

  it('工作量统计与导出走 /invigilation-workload,导出是文件下载', async () => {
    await getInvigilationWorkload(3)
    expect(lastUrl).toBe('/api/exam/exams/3/invigilation-workload')
    expect(lastMethod).toBe('GET')
    await exportInvigilationWorkload(3)
    expect(lastUrl).toBe('/api/exam/exams/3/invigilation-workload/export')
    expect(lastMethod).toBe('GET')
  })

  it('考风考纪记录增删改查走 /discipline,类型只有违纪、作弊、其他', async () => {
    expect(DISCIPLINE_TYPES).toEqual(['违纪', '作弊', '其他'])
    expect(INVIGILATION_ROLE).toBe('监考')
    await listDiscipline(3)
    expect(lastUrl).toBe('/api/exam/exams/3/discipline')
    expect(lastMethod).toBe('GET')
    await createDiscipline(3, { subject_id: 2, student_id: 4, type: '作弊', description: '考试中查看手机', handling: '取消该科成绩' })
    expect(lastUrl).toBe('/api/exam/exams/3/discipline')
    expect(lastMethod).toBe('POST')
    expect(lastBody).toMatchObject({ subject_id: 2, student_id: 4, type: '作弊' })
    await updateDiscipline(3, 9, { handling: '记过' })
    expect(lastUrl).toBe('/api/exam/exams/3/discipline/9')
    expect(lastMethod).toBe('PATCH')
    expect(lastBody).toMatchObject({ handling: '记过' })
    await deleteDiscipline(3, 9)
    expect(lastUrl).toBe('/api/exam/exams/3/discipline/9')
    expect(lastMethod).toBe('DELETE')
  })

  it('两视图切换逻辑:非法值回到教师视图,切换来回切', () => {
    expect(normalizeSheetView('room')).toBe('room')
    expect(normalizeSheetView('teacher')).toBe('teacher')
    expect(normalizeSheetView('bogus')).toBe('teacher')
    expect(normalizeSheetView(null)).toBe('teacher')
    expect(normalizeSheetView(undefined)).toBe('teacher')
    expect(toggleSheetView('teacher')).toBe('room')
    expect(toggleSheetView('room')).toBe('teacher')
    expect(SHEET_VIEW_LABELS.teacher).toBe('按教师视图')
    expect(SHEET_VIEW_LABELS.room).toBe('按考场视图')
  })
})

async function makeRouter() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/exam/exams/:id', name: 'exam-exam-detail', component: { template: '<div />' } },
      { path: '/exam/exams/:id/invigilation', name: 'exam-exam-invigilation', component: ExamInvigilation },
    ],
  })
  await router.push('/exam/exams/3/invigilation')
  await router.isReady()
  return router
}

async function mountPage() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.user = {
    id: 1, username: 'admin', display_name: '系统管理员', roles: ['admin'],
    must_change_password: false,
  }
  const Host = { render: () => h(NMessageProvider, () => h(ExamInvigilation)) }
  const wrapper = mount(Host, { global: { plugins: [pinia, await makeRouter()] } })
  await flushPromises()
  await flushPromises()
  await flushPromises()
  await flushPromises()
  return wrapper
}

describe('监考安排页(KW-23~29)', () => {
  it('默认按教师视图展示监考表,规则与教师池、工作量随页加载', async () => {
    const wrapper = await mountPage()
    expect(wrapper.text()).toContain('期中考试')
    expect(wrapper.text()).toContain('王老师')
    expect(wrapper.find('[data-testid="sheet-teacher-block"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="sheet-room-block"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('240')
  })

  it('一键排监考后 warnings 原样展示,不改写冲突与人选不足警告', async () => {
    const wrapper = await mountPage()
    await wrapper.find('[data-testid="invigilate-run"]').trigger('click')
    await flushPromises()
    await flushPromises()
    const box = wrapper.find('[data-testid="invigilate-warnings"]')
    expect(box.exists()).toBe(true)
    expect(box.text()).toContain('王老师与课表冲突，未排入数学场')
    expect(box.text()).toContain('201 考场人选不足，未排满 2 人')
    expect(wrapper.find('[data-testid="invigilate-result"]').text()).toContain('已安排监考 4 人次')
  })

  it('两视图切换:点按考场视图出考场表,再切回教师视图', async () => {
    const wrapper = await mountPage()
    await wrapper.find('[data-testid="sheet-view-room"]').trigger('click')
    await flushPromises()
    await flushPromises()
    expect(wrapper.find('[data-testid="sheet-room-block"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('201 考场')
    expect(wrapper.text()).toContain('李老师')
    expect(wrapper.find('[data-testid="sheet-teacher-block"]').exists()).toBe(false)
    await wrapper.find('[data-testid="sheet-view-teacher"]').trigger('click')
    await flushPromises()
    await flushPromises()
    expect(wrapper.find('[data-testid="sheet-teacher-block"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('王老师')
  })

  it('切换视图按钮来回切:教师视图点一次变考场视图', async () => {
    const wrapper = await mountPage()
    expect(wrapper.find('[data-testid="sheet-teacher-block"]').exists()).toBe(true)
    await wrapper.find('[data-testid="sheet-view-toggle"]').trigger('click')
    await flushPromises()
    await flushPromises()
    expect(wrapper.find('[data-testid="sheet-room-block"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('201 考场')
  })

  // 按 placeholder 找下拉(仓库里已有用 $emit('update:value') 驱动 n-select 的模式)。
  function findSelect(wrapper: VueWrapper, placeholder: string) {
    const sel = wrapper.findAllComponents(NSelect)
      .find((c) => c.props('placeholder') === placeholder)
    expect(sel?.exists()).toBe(true)
    return sel as NonNullable<typeof sel>
  }
  function emitSelectValue(
    sel: ReturnType<typeof findSelect>, value: number | number[],
  ) {
    ;(sel.vm as unknown as { $emit: (e: string, v: number | number[]) => void })
      .$emit('update:value', value)
  }
  function findButton(wrapper: VueWrapper, text: string) {
    const btn = wrapper.findAllComponents(NButton)
      .find((b) => b.text().trim() === text)
    expect(btn?.exists()).toBe(true)
    return btn as NonNullable<typeof btn>
  }

  it('手工添加监考:同一科目同一考场一次勾选两位教师,点一次确认走批量端点', async () => {
    bulkHits.length = 0
    const wrapper = await mountPage()
    await wrapper.find('[data-testid="invigilation-add"]').trigger('click')
    await flushPromises()
    emitSelectValue(findSelect(wrapper, '选择科目'), 2)
    emitSelectValue(findSelect(wrapper, '选择考场'), 12)
    emitSelectValue(findSelect(wrapper, '选择监考教师(可多选)'), [1, 2])
    await findButton(wrapper, '确认添加').trigger('click')
    await flushPromises()
    await flushPromises()
    // 确认添加后还会跑三次重载,lastBody 会被覆盖,用批量请求记录断言。
    expect(bulkHits.length).toBe(1)
    expect(bulkHits[0]).toMatchObject({ subject_id: 2, room_id: 12, teacher_ids: [1, 2], role: '监考' })
  })
})
