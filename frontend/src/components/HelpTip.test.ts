import { mount } from '@vue/test-utils'
import naive from 'naive-ui'
import { describe, expect, it } from 'vitest'
import HelpTip from './HelpTip.vue'

// 问号提示的统一写法:平时只显示一个小问号,说明文字挂在 hover 提示里。
// Naive 的 n-tooltip 在测试里是桩组件,故这里只钉触发器与 testid,
// 说明文字本身由各页面的文案负责(见各页的 help-* testid)。
describe('HelpTip', () => {
  it('只显示一个问号触发器,不抢眼', () => {
    const wrapper = mount(HelpTip, {
      props: { testid: 'help-demo' },
      slots: { default: '这段功能是干嘛的' },
      global: { plugins: [naive] },
    })
    const tip = wrapper.find('[data-testid="help-demo"]')
    expect(tip.exists()).toBe(true)
    expect(tip.text()).toBe('?')
    expect(tip.classes()).toContain('help-tip')
  })
})
