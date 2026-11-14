import { flushPromises, mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { createPinia, setActivePinia } from 'pinia'
import { h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import {
  canResendNotification, formatNotifyResult, getNotificationSettings,
  listNotifications, notifyInvigilation, notifySchedule,
  notifyScoreDeadline, remindDueNotifications, resendNotification,
  saveNotificationSettings, summarizeUnsubmittedScores,
} from '@/api/exam'
import type { ExamNotification, ScoreProgress } from '@/api/exam'
import ExamNotifications from './ExamNotifications.vue'
import { useAuthStore } from '@/stores/auth'

// fetch 打桩:记下最后一次请求的 URL、方法与 body;按 URL 回固定 JSON
let lastUrl = ''
let lastMethod = ''
let lastBody: unknown = null
const seenUrls: string[] = []
vi.stubGlobal('fetch', vi.fn((url: string, init: { method?: string; body?: string } = {}) => {
  lastUrl = url
  seenUrls.push(url)
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
  if (url.startsWith('/api/exam/exams/3/notification-settings')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        exam_id: 3, schedule_notify_enabled: true, invigilation_remind_enabled: true,
        score_deadline_remind_enabled: false,
      }),
    })
  }
  if (url.startsWith('/api/exam/exams/3/score-settings')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        exam_id: 3, entry_mode: 'total_only', makeup_mode: 'separate',
        cheating_score_mode: 'zero', absent_counts: false,
        score_deadline: '2026-11-20T17:00:00',
      }),
    })
  }
  if (url.startsWith('/api/exam/exams/3/score-progress')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        subjects: [{
          subject_id: 2, subject_name: '数学',
          classes: [
            { class_unit_id: 5, class_name: '七年二班', total: 40, entered: 40, submitted: 40, status: '已提交' },
            { class_unit_id: 6, class_name: '七年三班', total: 38, entered: 30, submitted: 0, status: '录入中' },
          ],
        }],
      }),
    })
  }
  if (url.startsWith('/api/exam/exams/3/notifications')) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        items: [
          {
            id: 1, exam_id: 3, notification_type: '考试日程', recipient_name: '张老师',
            channel: '钉钉', status: '失败', message: '考试日程通知', error: '无手机号',
            sent_at: null, created_at: '2026-11-14T01:00:00',
          },
          {
            id: 2, exam_id: 3, notification_type: '监考提醒', recipient_name: '李老师',
            channel: '钉钉', status: '成功', message: '监考提醒', error: null,
            sent_at: '2026-11-14T01:05:00', created_at: '2026-11-14T01:00:00',
          },
        ],
        total: 2,
      }),
    })
  }
  return Promise.resolve({
    ok: true, status: 200,
    json: () => Promise.resolve({ sent: 0, failed: 0 }),
  })
}))

function failedLog(over: Partial<ExamNotification> = {}): ExamNotification {
  return {
    id: 1, exam_id: 3, notification_type: '考试日程', recipient_name: '张老师',
    channel: '钉钉', status: '失败', message: '考试日程通知', error: '无手机号',
    sent_at: null, created_at: '2026-11-14T01:00:00',
    ...over,
  }
}

describe('通知与提醒 API 客户端(KW-57~59/61)', () => {
  it('通知设置查询与保存走 /notification-settings,保存带全部三项开关', async () => {
    await getNotificationSettings(3)
    expect(lastUrl).toBe('/api/exam/exams/3/notification-settings')
    expect(lastMethod).toBe('GET')
    await saveNotificationSettings(3, {
      schedule_notify_enabled: true, invigilation_remind_enabled: false,
      score_deadline_remind_enabled: true,
    })
    expect(lastUrl).toBe('/api/exam/exams/3/notification-settings')
    expect(lastMethod).toBe('PUT')
    expect(lastBody).toMatchObject({
      schedule_notify_enabled: true, invigilation_remind_enabled: false,
      score_deadline_remind_enabled: true,
    })
  })

  it('三类手动发送各走自己的 notify 端点,都回 sent/failed', async () => {
    await notifySchedule(3)
    expect(lastUrl).toBe('/api/exam/exams/3/notify/schedule')
    expect(lastMethod).toBe('POST')
    await notifyInvigilation(3)
    expect(lastUrl).toBe('/api/exam/exams/3/notify/invigilation')
    expect(lastMethod).toBe('POST')
    await notifyScoreDeadline(3)
    expect(lastUrl).toBe('/api/exam/exams/3/notify/score-deadline')
    expect(lastMethod).toBe('POST')
  })

  it('到期扫走全校端点 /notifications/remind-due,不带考试 id', async () => {
    await remindDueNotifications()
    expect(lastUrl).toBe('/api/exam/notifications/remind-due')
    expect(lastMethod).toBe('POST')
  })

  it('通知记录按类型/状态/关键词筛选,重发只走失败记录的 /resend 端点', async () => {
    await listNotifications(3, { type: '监考提醒', status: '失败', q: '张老师' })
    expect(lastUrl).toBe(
      '/api/exam/exams/3/notifications?type=%E7%9B%91%E8%80%83%E6%8F%90%E9%86%92&status=%E5%A4%B1%E8%B4%A5&q=%E5%BC%A0%E8%80%81%E5%B8%88',
    )
    await listNotifications(3)
    expect(lastUrl).toBe('/api/exam/exams/3/notifications')
    await resendNotification(3, 7)
    expect(lastUrl).toBe('/api/exam/exams/3/notifications/7/resend')
    expect(lastMethod).toBe('POST')
  })
})

describe('发送结果与重发的展示逻辑(KW-57~61)', () => {
  it('发送结果同时展示成功与失败人数,失败大于 0 时提示去记录里重发', () => {
    expect(formatNotifyResult({ sent: 12, failed: 0 })).toBe('成功 12 人,失败 0 人')
    expect(formatNotifyResult({ sent: 10, failed: 2 })).toBe(
      '成功 10 人,失败 2 人,失败的可在通知记录里重发',
    )
    expect(formatNotifyResult({ sent: 0, failed: 0 })).toBe('成功 0 人,失败 0 人')
  })

  it('只有失败记录可重发,成功与待发送不可重发', () => {
    expect(canResendNotification(failedLog({ status: '失败' }))).toBe(true)
    expect(canResendNotification(failedLog({ status: '成功' }))).toBe(false)
    expect(canResendNotification(failedLog({ status: '待发送' }))).toBe(false)
  })

  it('未录完汇总只数 submitted 小于 total 的班级与人数', () => {
    const progress: ScoreProgress = {
      subjects: [{
        subject_id: 2, subject_name: '数学',
        classes: [
          { class_unit_id: 5, class_name: '七年二班', total: 40, entered: 40, submitted: 40, status: '已提交' },
          { class_unit_id: 6, class_name: '七年三班', total: 38, entered: 30, submitted: 0, status: '录入中' },
          { class_unit_id: 7, class_name: '七年四班', total: 36, entered: 36, submitted: 20, status: '录入中' },
        ],
      }],
    }
    expect(summarizeUnsubmittedScores(progress)).toEqual({
      unsubmittedClasses: 2, unsubmittedStudents: 54,
    })
    expect(summarizeUnsubmittedScores({ subjects: [] })).toEqual({
      unsubmittedClasses: 0, unsubmittedStudents: 0,
    })
  })
})

describe('通知与提醒页分区渲染(KW-57~61)', () => {
  it('五个分区标题齐全,失败记录有重发按钮、成功记录没有,健康页提示在场', async () => {
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
        { path: '/exam/exams/:id/notifications', name: 'exam-exam-notifications', component: ExamNotifications },
        { path: '/settings/system', name: 'system', component: { template: '<div />' } },
      ],
    })
    await router.push('/exam/exams/3/notifications')
    await router.isReady()
    const Host = { render: () => h(NMessageProvider, () => h(ExamNotifications)) }
    const wrapper = mount(Host, { global: { plugins: [pinia, router] } })
    await flushPromises()
    await flushPromises()
    const text = wrapper.text()
    for (const title of ['通知设置', '考试日程通知', '监考提醒', '录分截止提醒', '通知记录']) {
      expect(text).toContain(title)
    }
    expect(text).toContain('期中考试')
    // 录分截止:截止时间与未录完班级/人数来自成绩设置与录分进度
    expect(text).toContain('未录完 1 个班级、38 人')
    // 健康页提示:聚合数据已进系统提醒健康页
    expect(text).toContain('考务通知的聚合数据已进系统提醒健康页')
    expect(wrapper.find('[data-testid="notifications-health-hint"]').exists()).toBe(true)
    // 失败记录可重发,成功记录不可重发
    expect(wrapper.find('[data-testid="notification-resend-1"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="notification-resend-2"]').exists()).toBe(false)
  })

  it('点发送日程通知后展示 sent/failed 结果', async () => {
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
        { path: '/exam/exams/:id/notifications', name: 'exam-exam-notifications', component: ExamNotifications },
        { path: '/settings/system', name: 'system', component: { template: '<div />' } },
      ],
    })
    await router.push('/exam/exams/3/notifications')
    await router.isReady()
    const Host = { render: () => h(NMessageProvider, () => h(ExamNotifications)) }
    const wrapper = mount(Host, { global: { plugins: [pinia, router] } })
    await flushPromises()
    await flushPromises()
    await wrapper.find('[data-testid="notifications-send-schedule"]').trigger('click')
    await flushPromises()
    await flushPromises()
    // 发送后页内自动刷新通知记录,所以用全部请求记录断言发送端点
    expect(seenUrls).toContain('/api/exam/exams/3/notify/schedule')
    expect(wrapper.find('[data-testid="notifications-result-schedule"]').text()).toContain('成功 0 人,失败 0 人')
  })
})
