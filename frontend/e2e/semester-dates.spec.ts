import { expect, test } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

/**
 * #15:学期没有起讫日期就不能登记请假,但界面上没有任何地方填得了——
 * 建立学期表单没有日期栏位、学期卡片没有编辑、设置精灵也不问,
 * 等于照正常流程建立的学期一定卡住,用户自己救不回来。
 */
const YEAR = 153
const START = '2026-08-30'
const END = '2027-01-20'

test('学期起讫日期:建立时可填,已建立的也能编辑补上', async ({ page }) => {
  test.setTimeout(120_000)
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)

  // 先用 API 建一个「没有日期」的学期,重现用户的处境
  const sem = await (await page.request.post('/api/semesters', {
    data: { academic_year: YEAR, term: 1, template_key: 'junior_high' },
  })).json()

  const teacher = await (await page.request.post(`/api/teachers?semester_id=${sem.id}`, {
    data: { name: '王师' },
  })).json()

  // 这种状态下请假会被挡,而且讯息要指路
  const blocked = await page.request.post(`/api/leaves?semester_id=${sem.id}`, {
    data: {
      teacher_id: teacher.id, leave_type: 'sick',
      start_date: '2026-10-07', end_date: '2026-10-07',
    },
    failOnStatusCode: false,
  })
  expect(blocked.status()).toBe(400)
  expect((await blocked.json()).detail).toContain('编辑学期')

  // 界面上看得出「尚未设置起讫日期」,而且有地方可以补
  await page.goto('/settings/semesters')
  const card = page.locator('.n-card').filter({ hasText: `${YEAR} 学年度第 1 学期` }).first()
  await expect(card.getByTestId('sem-no-range')).toBeVisible()
  await card.getByTestId('sem-edit').click()
  await page.getByTestId('sem-edit-start').locator('input').fill(START)
  await page.getByTestId('sem-edit-start').locator('input').press('Enter')
  await page.getByTestId('sem-edit-end').locator('input').fill(END)
  await page.getByTestId('sem-edit-end').locator('input').press('Enter')
  await page.getByTestId('sem-edit-save').click()
  await expect(page.getByText('学期已更新')).toBeVisible()
  await expect(card.getByTestId('sem-range')).toContainText(`${START} ~ ${END}`)

  // 补完之后请假就通了
  const ok = await page.request.post(`/api/leaves?semester_id=${sem.id}`, {
    data: {
      teacher_id: teacher.id, leave_type: 'sick',
      start_date: '2026-10-07', end_date: '2026-10-07',
    },
  })
  expect(ok.status(), '补上日期后应该可以登记请假').toBe(201)

  await deleteSemesterByYearTerm(page, YEAR, 1)
})

test('学期起讫日期:建立学期表单要求填日期,填了就直接带入', async ({ page }) => {
  test.setTimeout(120_000)
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR + 1, 1)

  await page.goto('/settings/semesters')
  const yearInput = page.locator('.n-input-number input').first()
  await yearInput.fill(String(YEAR + 1))
  await yearInput.press('Enter')

  // 没填日期就按建立 → 挡下来并说明原因
  await page.getByTestId('sem-create').click()
  await expect(page.getByText('请填学期起讫日期(请假与调代课需要)')).toBeVisible()

  await page.getByTestId('sem-start').locator('input').fill(START)
  await page.getByTestId('sem-start').locator('input').press('Enter')
  await page.getByTestId('sem-end').locator('input').fill(END)
  await page.getByTestId('sem-end').locator('input').press('Enter')
  await page.getByTestId('sem-create').click()
  await expect(page.getByText('学期已建立')).toBeVisible()

  const card = page.locator('.n-card').filter({ hasText: `${YEAR + 1} 学年度第 1 学期` }).first()
  await expect(card.getByTestId('sem-range')).toContainText(`${START} ~ ${END}`)

  await deleteSemesterByYearTerm(page, YEAR + 1, 1)
})
