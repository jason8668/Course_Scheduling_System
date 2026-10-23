import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

/**
 * 登录按一次只送一笔请求(用户回报 #39)。
 *
 * 先前按钮同时是表单的 submit 又挂了 @click,输入框也另外挂了 @keyup.enter,按一次送出两笔:
 * 输错密码一次算两次失败,约第 3 次就被锁定(门槛是连续 5 次)。
 * 用不存在的帐号测,不会动到任何帐号的失败次数。
 */
async function attempts(page: Page, submit: () => Promise<void>): Promise<number> {
  let count = 0
  page.on('request', (r) => {
    if (r.method() === 'POST' && r.url().endsWith('/api/auth/login')) count += 1
  })
  await page.goto('/login')
  await page.getByPlaceholder('请输入帐号').fill('no-such-user-39')
  await page.getByPlaceholder('请输入密码').fill('wrong-password')
  await submit()
  await expect(page.getByText(/帐号或密码错误|登录失败/).first()).toBeVisible()
  await page.waitForTimeout(500) // 多出来的那一笔若存在,这时也已送出
  return count
}

test('登录:点一次按钮只送一笔请求', async ({ page }) => {
  expect(await attempts(page, () => page.getByRole('button', { name: '登录' }).click())).toBe(1)
})

test('登录:在密码栏按 Enter 只送一笔请求', async ({ page }) => {
  expect(await attempts(page, () => page.getByPlaceholder('请输入密码').press('Enter'))).toBe(1)
})

test('登录:在帐号栏按 Enter 只送一笔请求', async ({ page }) => {
  expect(await attempts(page, () => page.getByPlaceholder('请输入帐号').press('Enter'))).toBe(1)
})
