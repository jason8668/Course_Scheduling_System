import type { Page } from '@playwright/test'

// 专用于 e2e 的教学组长帐号(由验收前置步骤以 docker exec 建立,不删除)。
export const E2E_USER = 'e2e_scheduler'
export const E2E_PASS = 'e2etest1234'

export async function login(page: Page, user = E2E_USER, pass = E2E_PASS): Promise<void> {
  await page.goto('/login')
  await page.getByPlaceholder('请输入帐号').fill(user)
  await page.getByPlaceholder('请输入密码').fill(pass)
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL((url) => !url.pathname.startsWith('/login'))
}

/** 删除指定学年度学期(idempotent),避免测试资料残留或冲突。 */
export async function deleteSemesterByYearTerm(page: Page, year: number, term: number): Promise<void> {
  const resp = await page.request.get('/api/semesters')
  const list = (await resp.json()) as Array<{ id: number; academic_year: number; term: number }>
  for (const s of list) {
    if (s.academic_year === year && s.term === term) {
      await page.request.delete(`/api/semesters/${s.id}`)
    }
  }
}
