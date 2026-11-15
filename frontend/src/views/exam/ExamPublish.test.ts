import { flushPromises, mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { createPinia, setActivePinia } from 'pinia'
import { h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import {
  approvalLevelLabel, canLockAfterProofreading, changeApprovalProgressText,
  closeObjection, createChangeRequest, createLock, createObjection, createPublishBatch,
  decideChangeRequest, decideProofreading, deleteLock, getPublishSettings,
  getPublishStatus, listChangeRequests, listLocks, listObjections, listProofreading,
  listPublishBatches, nextChangeApprovalLevel, publishDue, replyObjection,
  savePublishSettings, submitProofreading, withdrawPublishBatch,
} from '@/api/exam'
import type { Proofreading, ScoreChangeRequest } from '@/api/exam'
import ExamPublish from './ExamPublish.vue'
import { useAuthStore } from '@/stores/auth'

// fetch 打桩:记下最后一次请求的 URL、方法与 body;按 URL 回固定 JSON
let lastUrl = ''
let lastMethod = ''
let lastBody: unknown = null
vi.stubGlobal('fetch', vi.fn((url: string, init: { method?: string; body?: string } = {}) => {
  lastUrl = url
  lastMethod = init.method ?? 'GET'
  lastBody = init.body ? JSON.parse(init.body) : null
  if (url === '/api/exam/exams/3') {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        id: 3, semester_id: 1, name: '期中考试', exam_type: '期中', grades: [7],
        status: '成绩处理中', description: null, created_at: '2026-11-01',
        subjects: [{ subject_id: 2, subject_name: '数学', exam_date: null, start_time: null, end_time: null, full_score: 120 }],
        participant_count: 0,
      }),
    })
  }
  if (url.startsWith('/api/class-units')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve([
        { id: 5, semester_id: 1, grade: 7, name: '七年二班', track: '普通', department: null, student_count: 40, homeroom_teacher_id: null },
      ]),
    })
  }
  if (url.startsWith('/api/exam/exams/3/publish-settings')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        exam_id: 3, proofreader_role: 'subject_leader', approval_levels: 1,
        objection_open: true,
      }),
    })
  }
  if (url.startsWith('/api/exam/exams/3/proofreading')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        items: [{
          id: 1, exam_id: 3, subject_id: 2, subject_name: '数学', class_unit_id: null,
          class_name: null, submitted_by: 7, submitted_by_name: '张老师',
          proofreader_id: 8, proofreader_name: '李组长', status: '待校对', note: null,
        }],
        total: 1,
      }),
    })
  }
  if (url.startsWith('/api/exam/exams/3/publish-status')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({ exam_id: 3, batches: [], all_published: false }),
    })
  }
  return Promise.resolve({
    ok: true, status: 200,
    json: () => Promise.resolve({ items: [], total: 0, published: 0 }),
  })
}))

function proofItem(over: Partial<Proofreading>): Proofreading {
  return {
    id: 1, exam_id: 3, subject_id: 2, subject_name: '数学', class_unit_id: null,
    class_name: null, grade: null, submitted_by: 7, submitted_by_name: '张老师',
    proofreader_id: 8, proofreader_name: '李组长', status: '待校对', note: null,
    ...over,
  }
}

function changeReq(over: Partial<ScoreChangeRequest>): ScoreChangeRequest {
  return {
    id: 1, exam_id: 3, score_id: 7, student_name: '张三', subject_name: '数学',
    old_score: 88, new_score: 92, reason: '合分错误', status: '待审批',
    requested_by: 7, requested_by_name: '张老师', approvals: [],
    ...over,
  }
}

describe('发布与校对锁定 API 客户端(KW-36~40)', () => {
  it('发布设置查询与保存走 /publish-settings,带全部三项口径', async () => {
    await getPublishSettings(3)
    expect(lastUrl).toBe('/api/exam/exams/3/publish-settings')
    await savePublishSettings(3, {
      proofreader_role: 'peer_teacher', approval_levels: 2,
      objection_open: false,
    })
    expect(lastUrl).toBe('/api/exam/exams/3/publish-settings')
    expect(lastMethod).toBe('PUT')
    expect(lastBody).toMatchObject({
      proofreader_role: 'peer_teacher', approval_levels: 2,
      objection_open: false,
    })
  })

  it('校对列表带科目/班级参数,提交与决定走同一端点族', async () => {
    await listProofreading(3, { subjectId: 2, classUnitId: 5 })
    expect(lastUrl).toBe('/api/exam/exams/3/proofreading?subject_id=2&class_unit_id=5')
    await listProofreading(3)
    expect(lastUrl).toBe('/api/exam/exams/3/proofreading')
    await submitProofreading(3, { subject_id: 2, class_unit_id: 5, note: '请校对' })
    expect(lastUrl).toBe('/api/exam/exams/3/proofreading')
    expect(lastMethod).toBe('POST')
    expect(lastBody).toMatchObject({ subject_id: 2, class_unit_id: 5, note: '请校对' })
    await submitProofreading(3, { subject_id: 2 })
    expect(lastBody).toMatchObject({ subject_id: 2 })
    expect(lastBody).not.toHaveProperty('class_unit_id')
    await decideProofreading(3, 9, { decision: '通过' })
    expect(lastUrl).toBe('/api/exam/exams/3/proofreading/9/decide')
    expect(lastBody).toMatchObject({ decision: '通过' })
    await decideProofreading(3, 9, { decision: '退回', note: '合计有误' })
    expect(lastBody).toMatchObject({ decision: '退回', note: '合计有误' })
  })

  it('锁定列表、新增与解锁走 /locks,解锁为 DELETE', async () => {
    await listLocks(3)
    expect(lastUrl).toBe('/api/exam/exams/3/locks')
    await createLock(3, { subject_id: 2, class_unit_id: 5 })
    expect(lastUrl).toBe('/api/exam/exams/3/locks')
    expect(lastMethod).toBe('POST')
    expect(lastBody).toMatchObject({ subject_id: 2, class_unit_id: 5 })
    await createLock(3, { subject_id: 2 })
    expect(lastBody).toMatchObject({ subject_id: 2 })
    expect(lastBody).not.toHaveProperty('class_unit_id')
    await deleteLock(3, 4)
    expect(lastUrl).toBe('/api/exam/exams/3/locks/4')
    expect(lastMethod).toBe('DELETE')
  })

  it('改分申请按状态查、新增带原改后分数与原因、决定走 /decide', async () => {
    await listChangeRequests(3, '待审批')
    expect(lastUrl).toBe('/api/exam/exams/3/score-change-requests?status=%E5%BE%85%E5%AE%A1%E6%89%B9')
    await listChangeRequests(3)
    expect(lastUrl).toBe('/api/exam/exams/3/score-change-requests')
    await createChangeRequest(3, { score_id: 7, new_score: 92, reason: '合分错误' })
    expect(lastUrl).toBe('/api/exam/exams/3/score-change-requests')
    expect(lastMethod).toBe('POST')
    expect(lastBody).toMatchObject({ score_id: 7, new_score: 92, reason: '合分错误' })
    await createChangeRequest(3, { score_id: 8, reason: '取消成绩' })
    expect(lastBody).toMatchObject({ score_id: 8, new_score: null, reason: '取消成绩' })
    await decideChangeRequest(3, 5, { decision: '通过' })
    expect(lastUrl).toBe('/api/exam/exams/3/score-change-requests/5/decide')
    expect(lastBody).toMatchObject({ decision: '通过' })
    await decideChangeRequest(3, 5, { decision: '驳回', note: '证据不足' })
    expect(lastBody).toMatchObject({ decision: '驳回', note: '证据不足' })
  })

  it('发布批次查询、新建、撤回、到期发布与状态总览走同一端点族', async () => {
    await listPublishBatches(3)
    expect(lastUrl).toBe('/api/exam/exams/3/publish-batches')
    await createPublishBatch(3, { scope_type: '年级', scope_value: 7 })
    expect(lastUrl).toBe('/api/exam/exams/3/publish-batches')
    expect(lastMethod).toBe('POST')
    expect(lastBody).toMatchObject({ scope_type: '年级', scope_value: 7, publish_at: null })
    await createPublishBatch(3, {
      scope_type: '班级', scope_value: 5, publish_at: '2026-11-20T10:00', note: '先发七年二班',
    })
    expect(lastBody).toMatchObject({
      scope_type: '班级', scope_value: 5, publish_at: '2026-11-20T10:00', note: '先发七年二班',
    })
    await withdrawPublishBatch(3, 6, '发错范围')
    expect(lastUrl).toBe('/api/exam/exams/3/publish-batches/6/withdraw')
    expect(lastBody).toMatchObject({ note: '发错范围' })
    await publishDue(3)
    expect(lastUrl).toBe('/api/exam/exams/3/publish-due')
    expect(lastMethod).toBe('POST')
    await getPublishStatus(3)
    expect(lastUrl).toBe('/api/exam/exams/3/publish-status')
  })

  it('异议按状态查、登记、回复与关闭走同一端点族,关闭不带 body', async () => {
    await listObjections(3, '待复核')
    expect(lastUrl).toBe('/api/exam/exams/3/objections?status=%E5%BE%85%E5%A4%8D%E6%A0%B8')
    await createObjection(3, { score_id: 7, content: '选择题少算 4 分' })
    expect(lastUrl).toBe('/api/exam/exams/3/objections')
    expect(lastMethod).toBe('POST')
    expect(lastBody).toMatchObject({ score_id: 7, content: '选择题少算 4 分' })
    await replyObjection(3, 2, { reply: '已复核,补回 4 分' })
    expect(lastUrl).toBe('/api/exam/exams/3/objections/2/reply')
    expect(lastBody).toMatchObject({ reply: '已复核,补回 4 分' })
    await closeObjection(3, 2)
    expect(lastUrl).toBe('/api/exam/exams/3/objections/2/close')
    expect(lastMethod).toBe('POST')
  })
})

describe('校对通过才能锁定的状态流转(KW-36→KW-37)', () => {
  it('全科通过覆盖全部班级,单班通过只覆盖本班', () => {
    const items = [proofItem({ status: '通过', class_unit_id: null })]
    expect(canLockAfterProofreading(items, 2, 5)).toBe(true)
    expect(canLockAfterProofreading(items, 2, null)).toBe(true)
    const classPass = [proofItem({ status: '通过', class_unit_id: 5 })]
    expect(canLockAfterProofreading(classPass, 2, 5)).toBe(true)
    expect(canLockAfterProofreading(classPass, 2, 6)).toBe(false)
    expect(canLockAfterProofreading(classPass, 2, null)).toBe(false)
  })

  it('待校对与退回都不能锁定,其他科目通过也不能锁定本科目', () => {
    expect(canLockAfterProofreading([proofItem({ status: '待校对' })], 2, 5)).toBe(false)
    expect(canLockAfterProofreading([proofItem({ status: '退回' })], 2, 5)).toBe(false)
    expect(canLockAfterProofreading([proofItem({ status: '通过', subject_id: 3 })], 2, 5)).toBe(false)
    expect(canLockAfterProofreading([], 2, 5)).toBe(false)
  })
})

describe('改分审批两层的状态展示逻辑(KW-38)', () => {
  it('一层时层级文案为教研组长或教务,两层时分第一层教研组长、第二层教务', () => {
    expect(approvalLevelLabel(1, 1)).toBe('教研组长或教务')
    expect(approvalLevelLabel(1, 2)).toBe('第一层 · 教研组长')
    expect(approvalLevelLabel(2, 2)).toBe('第二层 · 教务')
  })

  it('两层审批:未审时下一层是第一层,一层通过后下一层是第二层,两层走完不再有下一层', () => {
    const fresh = changeReq({ approvals: [] })
    expect(nextChangeApprovalLevel(fresh, 2)).toBe(1)
    expect(changeApprovalProgressText(fresh, 2)).toContain('第一层 · 教研组长')
    const afterFirst = changeReq({
      approvals: [{ level: 1, approver_name: '李组长', decision: '通过', note: null }],
    })
    expect(nextChangeApprovalLevel(afterFirst, 2)).toBe(2)
    expect(changeApprovalProgressText(afterFirst, 2)).toContain('第二层 · 教务')
    const done = changeReq({
      status: '已通过',
      approvals: [
        { level: 1, approver_name: '李组长', decision: '通过', note: null },
        { level: 2, approver_name: '王教务', decision: '通过', note: null },
      ],
    })
    expect(nextChangeApprovalLevel(done, 2)).toBeNull()
    expect(changeApprovalProgressText(done, 2)).toBe('已通过(共 2 层)')
  })

  it('一层审批:一次通过即终结;任一层驳回即终结,进度写明已审层数', () => {
    const fresh = changeReq({ approvals: [] })
    expect(nextChangeApprovalLevel(fresh, 1)).toBe(1)
    expect(changeApprovalProgressText(fresh, 1)).toContain('教研组长或教务')
    const rejected = changeReq({
      status: '已驳回',
      approvals: [{ level: 1, approver_name: '李组长', decision: '驳回', note: '证据不足' }],
    })
    expect(nextChangeApprovalLevel(rejected, 2)).toBeNull()
    expect(changeApprovalProgressText(rejected, 2)).toBe('已驳回(已审批 1 层)')
  })
})

describe('发布与校对锁定页分区渲染', () => {
  it('六个分区标题齐全,校对未通过时锁定按钮置灰并提示不能锁定', async () => {
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
        { path: '/exam/exams/:id', name: 'exam-exam-detail', component: { template: '<div />' } },
        { path: '/exam/exams/:id/publish', name: 'exam-exam-publish', component: ExamPublish },
      ],
    })
    await router.push('/exam/exams/3/publish')
    await router.isReady()
    const Host = { render: () => h(NMessageProvider, () => h(ExamPublish)) }
    const wrapper = mount(Host, { global: { plugins: [pinia, router] } })
    await flushPromises()
    await flushPromises()
    const text = wrapper.text()
    for (const title of ['发布设置', '双人校对确认', '提交与锁定', '改分审批', '成绩分批发布', '查分与成绩异议登记']) {
      expect(text).toContain(title)
    }
    expect(text).toContain('期中考试')
    expect(text).toContain('待校对')
    const lockHint = wrapper.find('[data-testid="lock-not-ready"]')
    expect(lockHint.exists()).toBe(true)
    expect(lockHint.text()).toContain('该范围校对尚未通过,不能锁定')
    expect(wrapper.find('[data-testid="publish-all-published"]').text()).toContain('未全部发布')
  })
})
