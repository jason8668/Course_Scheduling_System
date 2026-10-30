import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import MySubstitutionSection from './MySubstitutionSection.vue'

describe('MySubstitutionSection', () => {
  it('显示本月代课节数', async () => {
    vi.stubGlobal('fetch', vi.fn(() =>
      Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({
        summaries: [{ handled_count: 3, billable_count: 2 }], details: [],
      }) })))
    const wrapper = mount(MySubstitutionSection, { props: { semesterId: 1 } })
    await flushPromises()
    expect(wrapper.text()).toContain('我的代课')
    expect(wrapper.text()).toContain('3 节')
  })
})
