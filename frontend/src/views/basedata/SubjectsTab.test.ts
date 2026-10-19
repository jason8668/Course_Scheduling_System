import { flushPromises, mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import SubjectsTab from './SubjectsTab.vue'

const fakeSubjects = [
  { id: 1, semester_id: 1, name: '数学', domain: '数学领域', required_room_type: null, default_block_size: 2 },
  { id: 2, semester_id: 1, name: '国文', domain: null, required_room_type: null, default_block_size: 1 },
]

vi.stubGlobal('fetch', vi.fn(() =>
  Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(fakeSubjects) }),
))

describe('SubjectsTab', () => {
  it('载入并显示科目清单', async () => {
    const Host = { render: () => h(NMessageProvider, () => h(SubjectsTab, { semesterId: 1 })) }
    const wrapper = mount(Host)
    await flushPromises()
    expect(wrapper.text()).toContain('数学')
    expect(wrapper.text()).toContain('国文')
    expect(wrapper.text()).toContain('2 连堂')
  })
})
