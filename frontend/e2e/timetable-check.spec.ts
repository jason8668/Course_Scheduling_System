import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

/**
 * 课表检查(用户回报 #40、#41)。
 *
 * 课表排好之后才把那一节设成教师「不可排」:
 *  - 储存规则当下就提示有哪几节课落在不可排时段(#41)
 *  - 「版本与发布」可以检查课表,列出冲突;发布前也会挡下,确认后才发布(#40)
 */
const YEAR = 158

const post = async (page: Page, url: string, data: object) => {
  const r = await page.request.post(url, { data })
  expect(r.ok(), `${url} -> ${r.status()} ${await r.text()}`).toBeTruthy()
  return r.json()
}

async function selectSemester(page: Page) {
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${YEAR} 学年度第 1 学期` }).click()
}

test('课表检查:事后设不可排时段会当场提示;检查课表与发布都列出冲突', async ({ page }) => {
  test.setTimeout(120_000)
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)
  const sem = await post(page, '/api/semesters', { academic_year: YEAR, term: 1, template_key: 'junior_high' })
  const q = `?semester_id=${sem.id}`

  try {
    const c = await post(page, `/api/class-units${q}`, { grade: 7, name: '701', track: 'junior_high' })
    const s = await post(page, `/api/subjects${q}`, { name: '检查国文' })
    const t = await post(page, `/api/teachers${q}`, { name: '检查王师' })
    const a = await post(page, `/api/assignments${q}`, {
      class_id: c.id, subject_id: s.id, periods_per_week: 1,
      teachers: [{ teacher_id: t.id, is_lead: true }], block_rules: [],
    })
    const tt = await post(page, `/api/timetables${q}`, { name: '草稿A' })
    const periods: { weekday: number; name: string; period_no: number }[] =
      (await (await page.request.get(`/api/class-units/${c.id}/period-table`)).json()).periods
    const second = periods.find((p) => p.weekday === 3 && p.name === '第二节')!.period_no
    await post(page, `/api/timetables/${tt.id}/entries`,
      { course_assignment_id: a.id, weekday: 3, period_no: second, span: 1 })

    // 一、课表排满、没有冲突 → 检查通过
    await page.goto('/scheduling/versions')
    await selectSemester(page)
    const row = page.locator('[data-testid="v-row-草稿A"]')
    await row.getByTestId('v-check').click()
    await expect(page.getByTestId('v-check-text')).toContainText('课务已排完(1/1 节),没有冲突')
    await expect(page.locator('.n-modal')).toBeHidden()

    // 二、到教师的时段规则,把周三第二节设成不可排 → 储存当下就提示(#41)
    await page.goto('/basedata')
    await selectSemester(page)
    await page.locator('tr', { hasText: '检查王师' }).getByRole('button', { name: '时段规则' }).click()
    const grid = page.locator('.rule-grid')
    await expect(grid).toBeVisible()
    await grid.locator('tr', { has: page.locator('td.rowhead', { hasText: /^第二节$/ }) })
      .locator('td.cell').nth(2).click() // 第 3 栏 = 周三;点一下 = 不可排
    await page.getByTestId('tr-save').click()
    const warn = page.getByTestId('tr-conflicts')
    await expect(warn).toBeVisible()
    await expect(warn).toContainText('规则已储存')
    await expect(warn).toContainText('草稿A(草稿)')
    await expect(page.getByTestId('tr-conflict')).toHaveText(['周三第二节 701 检查国文'])
    await page.getByTestId('tr-close').click()
    await expect(grid).toBeHidden()

    // 三、检查课表 → 列出冲突(#40);这个视窗只能关闭,不会发布
    await page.goto('/scheduling/versions')
    await selectSemester(page)
    await row.getByTestId('v-check').click()
    await expect(page.getByTestId('v-check-text')).toContainText('有 1 项冲突')
    const issues = page.getByTestId('v-issues')
    await expect(issues).toContainText('教师不可排时段')
    await expect(page.getByTestId('v-issue')).toContainText(['检查王师'])
    await expect(page.getByTestId('v-force-publish')).toHaveCount(0)
    await page.getByTestId('v-warn-close').click()
    await expect(issues).toBeHidden()

    // 四、发布 → 先列出冲突,确认后才发布
    await row.getByTestId('v-publish').click()
    await expect(issues).toContainText('教师不可排时段')
    await expect(page.getByTestId('v-unplaced')).toHaveCount(0) // 课务有排完,不该出现未排清单
    await expect(page.getByTestId('v-status-草稿A')).toHaveText('草稿')
    await page.getByTestId('v-force-publish').click()
    await expect(page.getByTestId('v-status-草稿A')).toHaveText('已发布')
  } finally {
    await deleteSemesterByYearTerm(page, YEAR, 1)
  }
})
