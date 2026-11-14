import { describe, expect, it, vi } from 'vitest'
import {
  ARRANGEMENT_LOCKED_HINT,
  ARRANGEMENT_MODE_LABELS,
  S_SHAPE_NO_SCORE_WARNING,
  addExamRoom,
  arrangeExam,
  canEditArrangement,
  deleteExamRoom,
  exportArrangements,
  getArrangementLock,
  getArrangementRule,
  getSeatMap,
  listArrangements,
  listExamRooms,
  lockArrangement,
  moveArrangement,
  saveArrangementRule,
  swapArrangements,
  unlockArrangement,
} from './exam'

// fetch 打桩:记下最后一次请求的 URL、方法与 body,回固定 JSON
let lastUrl = ''
let lastMethod = ''
let lastBody: unknown = null
// jsdom 里 a.click() 会触发导航报错:下载链接点击在此处是无操作桩
vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
vi.stubGlobal('URL', {
  createObjectURL: () => 'blob:fake',
  revokeObjectURL: () => {},
})
vi.stubGlobal('fetch', vi.fn((url: string, init: { method?: string; body?: string }) => {
  lastUrl = url
  lastMethod = init.method ?? 'GET'
  lastBody = init.body ? JSON.parse(init.body) : null
  if (url.includes('/arrangements/export')) {
    return Promise.resolve({
      ok: true,
      status: 200,
      headers: { get: () => null },
      blob: () => Promise.resolve(new Blob(['x'])),
    })
  }
  return Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve({
      items: [], total: 0, assigned: 120, rooms_used: 4,
      warnings: ['暂无上次成绩，暂按学号顺序编排'],
      locked: false, mode: 's_shape', scatter_same_class: true, max_per_room: 30, rooms: [],
    }),
  })
}))

describe('考场编排 API 客户端(KW-15~22)', () => {
  it('考场列表、新增、删除走契约端点', async () => {
    await listExamRooms(3)
    expect(lastUrl).toBe('/api/exam/exams/3/rooms')
    expect(lastMethod).toBe('GET')
    await addExamRoom(3, { room_id: 12, capacity: 30, room_type: 'normal', is_special: false })
    expect(lastUrl).toBe('/api/exam/exams/3/rooms')
    expect(lastMethod).toBe('POST')
    expect(lastBody).toMatchObject({ room_id: 12, capacity: 30, room_type: 'normal', is_special: false })
    await deleteExamRoom(3, 7)
    expect(lastUrl).toBe('/api/exam/exams/3/rooms/7')
    expect(lastMethod).toBe('DELETE')
  })

  it('编排规则查询与保存走 /arrangement-rule,模式三选一', async () => {
    // 补遗:清单 KW-16 原文三选一是整班/S 型/随机,旧 student_no/class_mixed 已删
    expect(Object.keys(ARRANGEMENT_MODE_LABELS).sort()).toEqual(['random', 's_shape', 'whole_class'])
    expect(ARRANGEMENT_MODE_LABELS.s_shape).toBe('按成绩S型混排')
    expect(ARRANGEMENT_MODE_LABELS.whole_class).toBe('按班级整班入考场')
    expect(ARRANGEMENT_MODE_LABELS.random).toBe('随机混排')
    await getArrangementRule(3)
    expect(lastUrl).toBe('/api/exam/exams/3/arrangement-rule')
    expect(lastMethod).toBe('GET')
    await saveArrangementRule(3, { mode: 's_shape', scatter_same_class: true, max_per_room: 30 })
    expect(lastUrl).toBe('/api/exam/exams/3/arrangement-rule')
    expect(lastMethod).toBe('PUT')
    expect(lastBody).toMatchObject({ mode: 's_shape', scatter_same_class: true, max_per_room: 30 })
  })

  it('自动编排走 POST /arrange:不选科目发空对象,选科目带 subject_id', async () => {
    await arrangeExam(3)
    expect(lastUrl).toBe('/api/exam/exams/3/arrange')
    expect(lastMethod).toBe('POST')
    expect(lastBody).toEqual({})
    await arrangeExam(3, 2)
    expect(lastBody).toMatchObject({ subject_id: 2 })
  })

  it('编排结果、座位表、导出走契约端点,检索参数只带 subject_id/room_id', async () => {
    await listArrangements(3, { subjectId: 2, roomId: 12 })
    expect(lastUrl).toBe('/api/exam/exams/3/arrangements?subject_id=2&room_id=12')
    await listArrangements(3)
    expect(lastUrl).toBe('/api/exam/exams/3/arrangements')
    await getSeatMap(3, 2)
    expect(lastUrl).toBe('/api/exam/exams/3/seat-map?subject_id=2')
    await getSeatMap(3)
    expect(lastUrl).toBe('/api/exam/exams/3/seat-map')
    await exportArrangements(3, 2)
    expect(lastUrl).toBe('/api/exam/exams/3/arrangements/export?subject_id=2')
    expect(lastMethod).toBe('GET')
  })

  it('换考场与互换座位走契约端点', async () => {
    await moveArrangement(3, { assignment_id: 11, to_room_id: 12, seat_no: 5 })
    expect(lastUrl).toBe('/api/exam/exams/3/arrangements/move')
    expect(lastMethod).toBe('POST')
    expect(lastBody).toMatchObject({ assignment_id: 11, to_room_id: 12, seat_no: 5 })
    await moveArrangement(3, { assignment_id: 11, to_room_id: 13 })
    expect(lastBody).toMatchObject({ assignment_id: 11, to_room_id: 13 })
    await swapArrangements(3, { assignment_id_a: 11, assignment_id_b: 12 })
    expect(lastUrl).toBe('/api/exam/exams/3/arrangements/swap')
    expect(lastMethod).toBe('POST')
    expect(lastBody).toMatchObject({ assignment_id_a: 11, assignment_id_b: 12 })
  })

  it('锁定、解锁、查锁定状态走契约端点', async () => {
    await lockArrangement(3, '编排已确认')
    expect(lastUrl).toBe('/api/exam/exams/3/arrangement-lock')
    expect(lastMethod).toBe('POST')
    expect(lastBody).toMatchObject({ note: '编排已确认' })
    await unlockArrangement(3)
    expect(lastUrl).toBe('/api/exam/exams/3/arrangement-unlock')
    expect(lastBody).toMatchObject({ note: null })
    await getArrangementLock(3)
    expect(lastUrl).toBe('/api/exam/exams/3/arrangement-lock')
    expect(lastMethod).toBe('GET')
  })

  it('S 型无成绩警告文案与后端原样一致,前端不得改写', () => {
    expect(S_SHAPE_NO_SCORE_WARNING).toBe('暂无上次成绩，暂按学号顺序编排')
  })

  it('锁定态按钮置灰逻辑:锁定不可编辑,未锁定可编辑;提示文案固定', () => {
    expect(ARRANGEMENT_LOCKED_HINT).toBe('已锁定，请先解锁')
    expect(canEditArrangement(true)).toBe(false)
    expect(canEditArrangement(false)).toBe(true)
  })
})
