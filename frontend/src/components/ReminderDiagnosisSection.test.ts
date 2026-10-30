import { createPinia } from 'pinia'
import { mount } from '@vue/test-utils'
import naive, { NMessageProvider } from 'naive-ui'
import { h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import ReminderDiagnosisSection from './ReminderDiagnosisSection.vue'

vi.mock('@/api/semesters', () => ({
  listSemesters: vi.fn().mockResolvedValue([{ id: 1, label: '2026 秋' }]),
}))
vi.mock('@/api/basedata', () => ({
  listTeachers: vi.fn().mockResolvedValue([{ id: 7, name: '丁静' }]),
}))
vi.mock('@/api/reminderDiagnosis', () => ({
  diagnoseReminder: vi.fn().mockResolvedValue({
    teacher_id: 7, teacher_name: '丁静', date: '2026-10-29', period_no: 1,
    steps: [
      { key: 'slot_exists', label: '该节实际有课', status: 'ok', detail: '七年级1班《数学》' },
      { key: 'phone', label: '手机号', status: 'fail', detail: '教师档案里没有手机号' },
    ],
    conclusion: '断在:手机号。',
  }),
  testSendReminder: vi.fn().mockResolvedValue({ ok: true, teacher_name: '丁静' }),
}))

async function flush() {
  await new Promise((r) => setTimeout(r, 0))
}

describe('ReminderDiagnosisSection', () => {
  it('点开始诊断后列出每一步与结论', async () => {
    const wrapper = mount(NMessageProvider, {
      global: { plugins: [naive, createPinia()] },
      slots: { default: () => h(ReminderDiagnosisSection) },
    })
    await flush()
    await wrapper.vm.$nextTick()
    const run = wrapper.find('[data-testid="diag-run"]')
    expect(run.exists()).toBe(true)
    await run.trigger('click')
    await flush()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="diag-conclusion"]').text()).toContain('断在:手机号')
    expect(wrapper.text()).toContain('该节实际有课')
  })
})
