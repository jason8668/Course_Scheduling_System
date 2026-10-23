import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { SEM_END, SEM_START } from './dates'
import { deleteSemesterByYearTerm, login } from './helpers'

// M6-3 验收:一门「完全排不下」的课(教师整周不可排)不会让部分排课整锅失败,
// 而是列进未排清单并说明原因;force 发布后,版本页的完整性报告仍讲得出那个原因
// (未排清单存进 DB,不再只活在 Redis 24h)。

const SHOTS = 'e2e/screenshots'
const YEAR = 151

const post = async (page: Page, url: string, data: object) =>
  (await page.request.post(url, { data })).json()
const get = async (page: Page, url: string) => (await page.request.get(url)).json()

test('部分排课:完全排不下的课列入未排清单并说明原因,发布后仍查得到', async ({ page }) => {
  test.setTimeout(180_000)
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)

  const sem = await post(page, '/api/semesters', {
    academic_year: YEAR, term: 1, template_key: 'junior_high',
    start_date: SEM_START, end_date: SEM_END,
  })
  const sid = sem.id
  const cls = await post(page, `/api/class-units?semester_id=${sid}`,
    { grade: 7, name: '701', track: 'junior_high' })

  // ① 正常课:排得进去
  const chinese = await post(page, `/api/subjects?semester_id=${sid}`, { name: '国文' })
  const wang = await post(page, `/api/teachers?semester_id=${sid}`,
    { name: '王师', base_periods: 20 })
  await post(page, `/api/assignments?semester_id=${sid}`, {
    class_id: cls.id, subject_id: chinese.id, periods_per_week: 4,
    teachers: [{ teacher_id: wang.id }], block_rules: [],
  })

  // ② 完全排不下的课:美术老师整周每一格都设为「不可排」
  const art = await post(page, `/api/subjects?semester_id=${sid}`, { name: '美术' })
  const lin = await post(page, `/api/teachers?semester_id=${sid}`,
    { name: '林师', base_periods: 20 })
  const table = await get(page, `/api/class-units/${cls.id}/period-table`)
  await page.request.put(`/api/teachers/${lin.id}/time-rules`, {
    data: table.periods.map((p: { weekday: number; period_no: number }) => ({
      weekday: p.weekday, period_no: p.period_no, rule_type: 'unavailable',
    })),
  })
  await post(page, `/api/assignments?semester_id=${sid}`, {
    class_id: cls.id, subject_id: art.id, periods_per_week: 2,
    teachers: [{ teacher_id: lin.id }], block_rules: [],
  })

  await post(page, `/api/timetables?semester_id=${sid}`, { name: '草稿A' })

  // ── 自动排课页:勾选部分排课(来源草稿由页面自己选)──
  await page.goto(`/scheduling/auto?semester_id=${sid}`)
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${YEAR} 学年度第 1 学期` }).click()
  await page.getByTestId('as-partial').click()
  await page.getByTestId('as-start').click()

  await expect(page.getByTestId('as-status')).toHaveText('已完成', { timeout: 120_000 })

  // 未排清单要列出美术,并说得出为什么(这正是旧版整锅失败的那门课)
  const unscheduled = page.getByTestId('as-unscheduled')
  await expect(unscheduled).toBeVisible()
  await expect(unscheduled).toContainText('美术')
  await expect(unscheduled).toContainText('找不到任何可排的')
  // 其他课照排(部分排课存在的意义)
  await expect(unscheduled).not.toContainText('国文')
  await page.screenshot({ path: `${SHOTS}/m63-1-unscheduled-reason.png` })

  // ── 版本页:force 发布,完整性报告仍讲得出原因(持久化,不靠 Redis)──
  const versions = await get(page, `/api/timetables?semester_id=${sid}`)
  const result = versions.find((v: { name: string }) => v.name.includes('部分排课结果'))
  expect(result, '应产出部分排课结果草稿').toBeTruthy()

  await page.goto(`/scheduling/versions?semester_id=${sid}`)
  await page.locator(`[data-testid="v-row-${result.name}"]`).getByTestId('v-publish').click()
  const unplaced = page.getByTestId('v-unplaced')
  await expect(unplaced).toContainText('美术')
  await expect(unplaced).toContainText('找不到任何可排的')
  await page.screenshot({ path: `${SHOTS}/m63-2-publish-warning-reason.png` })
  await page.getByTestId('v-force-publish').click()

  // 发布之后再查一次:原因还在(先前这份纪录 24h 后就消失了)
  const report = await get(page, `/api/timetables/${result.id}/completeness`)
  const artItem = report.unplaced.find((u: { subject: string }) => u.subject === '美术')
  expect(artItem.remaining).toBe(2)
  expect(artItem.reason).toContain('找不到任何可排的')

  await deleteSemesterByYearTerm(page, YEAR, 1)
})
