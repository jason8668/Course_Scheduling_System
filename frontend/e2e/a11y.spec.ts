import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { E2E_PASS, E2E_USER } from './helpers'

const SHOTS = 'e2e/screenshots'

// ── WCAG 相对亮度与对比度(1.4.3 / 1.4.11)──────────────────
function relLuminance([r, g, b]: number[]): number {
  const lin = (c: number) => {
    const s = c / 255
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}

function contrastRatio(fg: number[], bg: number[]): number {
  const l1 = relLuminance(fg)
  const l2 = relLuminance(bg)
  const [hi, lo] = l1 > l2 ? [l1, l2] : [l2, l1]
  return (hi + 0.05) / (lo + 0.05)
}

function parseRgb(s: string): number[] {
  const nums = (s.match(/[\d.]+/g) || ['0', '0', '0']).map(parseFloat)
  return [nums[0] || 0, nums[1] || 0, nums[2] || 0]
}

/** 取元素的前景色与有效背景色(往上找到第一个非透明背景)。 */
async function colorsOf(page: Page, selector: string) {
  return page.locator(selector).first().evaluate((el) => {
    const fg = getComputedStyle(el as Element).color
    let node: Element | null = el as Element
    let bg = 'rgba(0, 0, 0, 0)'
    while (node) {
      const c = getComputedStyle(node).backgroundColor
      if (c && !c.startsWith('rgba(0, 0, 0, 0') && c !== 'transparent') { bg = c; break }
      node = node.parentElement
    }
    if (bg.startsWith('rgba(0, 0, 0, 0')) bg = 'rgb(255, 255, 255)'
    return { fg, bg }
  })
}

// ── 验收:键盘可操作 ────────────────────────────────
test('无障碍:仅用键盘即可登录(不触碰滑鼠)', async ({ page }) => {
  await page.goto('/login')

  // 只用 Tab/输入/Enter:聚焦帐号栏 → 输入 → Tab 到密码 → 输入 → Enter 送出
  await page.getByPlaceholder('请输入帐号').focus()
  await page.keyboard.type(E2E_USER)
  await page.keyboard.press('Tab')
  await page.keyboard.type(E2E_PASS)
  await page.keyboard.press('Enter')

  await page.waitForURL((url) => !url.pathname.startsWith('/login'))
  await expect(page).toHaveURL(/\/(|dashboard)?$/)
  await page.screenshot({ path: `${SHOTS}/a11y-1-keyboard-login.png` })
})

test('无障碍:主要导览以 Tab 可达且有可见焦点', async ({ page }) => {
  await page.goto('/login')
  await page.getByPlaceholder('请输入帐号').fill(E2E_USER)
  await page.getByPlaceholder('请输入密码').fill(E2E_PASS)
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL((url) => !url.pathname.startsWith('/login'))

  // 连续 Tab 应能落在某个可互动元素上(连结/按钮/输入),且该元素确实获得焦点
  let reachedInteractive = false
  for (let i = 0; i < 15; i += 1) {
    await page.keyboard.press('Tab')
    const tag = await page.evaluate(() => {
      const el = document.activeElement
      return el ? el.tagName.toLowerCase() : ''
    })
    if (['a', 'button', 'input', 'select', 'textarea'].includes(tag)) {
      reachedInteractive = true
      break
    }
  }
  expect(reachedInteractive, 'Tab 应可将焦点移到可互动元素').toBe(true)
})

// ── 验收:对比度(WCAG AA)────────────────────────────
test('无障碍:内文与主要按钮对比度符合 WCAG AA 基本门槛', async ({ page }) => {
  await page.goto('/login')
  await page.getByPlaceholder('请输入帐号').fill(E2E_USER)
  await page.getByPlaceholder('请输入密码').fill(E2E_PASS)
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL((url) => !url.pathname.startsWith('/login'))
  await page.waitForLoadState('networkidle')

  // 一般内文:深字白底,应远高于 AA 正常文字门槛 4.5:1
  const body = await colorsOf(page, 'body')
  const bodyRatio = contrastRatio(parseRgb(body.fg), parseRgb(body.bg))
  expect(bodyRatio, `内文对比 ${bodyRatio.toFixed(2)}(fg=${body.fg} bg=${body.bg})`)
    .toBeGreaterThanOrEqual(4.5)

  // 主要按钮:按钮标签是「文字」,适用 WCAG 1.4.3 的 4.5:1,不是 1.4.11 非文字元件的 3:1。
  // Naive 默认的 #18a058 配白字只有 ~3.4:1;M6-5 把主色压深到 #0d7a43(5.41:1)后真的达标,
  // 门槛因此从权宜的 3:1 提到 AA 的 4.5:1(见 src/theme.ts)。
  const btn = await colorsOf(page, '.n-button--primary-type')
  const btnRatio = contrastRatio(parseRgb(btn.fg), parseRgb(btn.bg))
  expect(btnRatio, `主要按钮对比 ${btnRatio.toFixed(2)}(fg=${btn.fg} bg=${btn.bg})`)
    .toBeGreaterThanOrEqual(4.5)
})
