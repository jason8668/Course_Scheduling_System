import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { NEXT_MON, SEM_END, SEM_START, WED, WED2, withWeekday } from './dates'
import { deleteSemesterByYearTerm, login } from './helpers'

const SHOTS = 'e2e/screenshots'
const PENDING_ORANGE = 'rgb(240, 160, 32)'

const post = async (page: Page, url: string, data: object) =>
  (await page.request.post(url, { data })).json()

async function selectSemester(page: Page, year: number) {
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${year} 学年度第 1 学期` }).click()
}

/** Naive UI 的日期输入:填字串再按 Enter 才会落值。 */
async function fillDate(page: Page, testId: string, value: string) {
  const input = page.getByTestId(testId).locator('input')
  await input.click()
  await input.fill(value)
  await input.press('Enter')
}

/** 王师周三 5 节国文;课表已发布(请假只看已发布课表)。 */
async function seedPublishedSchool(page: Page, year: number) {
  const sem = await post(page, '/api/semesters', {
    academic_year: year, term: 1, template_key: 'junior_high',
    start_date: SEM_START, end_date: SEM_END,
  })
  const sid = sem.id
  const subjects: Record<string, number> = {}
  for (const s of await (await page.request.get(`/api/subjects?semester_id=${sid}`)).json()) {
    subjects[s.name] = s.id
  }
  const wang = await post(page, `/api/teachers?semester_id=${sid}`,
    { name: '王师', base_periods: 20 })
  const tt = await post(page, `/api/timetables?semester_id=${sid}`, { name: '草稿A' })

  const classes: number[] = []
  for (let i = 1; i <= 5; i += 1) {
    classes.push((await post(page, `/api/class-units?semester_id=${sid}`,
      { grade: 7, name: `70${i}`, track: 'junior_high' })).id)
  }
  const table = await (await page.request.get(
    `/api/class-units/${classes[0]}/period-table`)).json()
  const wed = table.periods
    .filter((p: { weekday: number; type: string }) => p.weekday === 3 && p.type === 'regular')
    .slice(0, 5)

  for (const [i, cid] of classes.entries()) {
    const a = await post(page, `/api/assignments?semester_id=${sid}`, {
      class_id: cid, subject_id: subjects['国文'], periods_per_week: 1,
      teachers: [{ teacher_id: wang.id }], block_rules: [],
    })
    await page.request.post(`/api/timetables/${tt.id}/entries`, {
      data: { course_assignment_id: a.id, weekday: 3, period_no: wed[i].period_no, span: 1 },
    })
  }
  await page.request.post(`/api/timetables/${tt.id}/publish?force=true`)
  return { sid, teacherId: wang.id as number }
}

// ── 验收①③:整天假展开 5 节 → 销假级联取消 ──
test('请假登记:组长代登整天假,展开受影响节次,销假后级联取消', async ({ page }) => {
  test.setTimeout(120_000)
  const YEAR = 138
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)
  await seedPublishedSchool(page, YEAR)

  await page.goto('/leaves')
  await selectSemester(page, YEAR)

  // 代登:选教师 → 假别 → 日期
  await page.getByTestId('lv-teacher').click()
  await page.locator('.n-base-select-option', { hasText: '王师' }).click()
  await fillDate(page, 'lv-start', WED) // 周三
  await fillDate(page, 'lv-end', WED)
  await page.getByTestId('lv-reason').locator('input').fill('流感')
  await page.getByTestId('lv-submit').click()

  // 周三整天 → 5 节课,节次一律显示节次表的名称
  const card = page.getByTestId('lv-card').first()
  await expect(card).toContainText(`王师 · 病假 · ${withWeekday(WED)} 整天`)
  await expect(page.getByTestId('lv-pending').first()).toHaveText('待处理 5 节')

  const table = page.getByTestId('lv-affected').first()
  await expect(table.locator('tbody tr')).toHaveCount(5)
  await expect(table).toContainText('第一节')
  await expect(table).toContainText('701')
  await expect(table).toContainText('国文')
  await expect(table).toContainText(withWeekday(WED))  // 没有星期就看不出为什么只有这天有课
  await page.screenshot({ path: `${SHOTS}/leave-1-affected.png` })

  // 销假 → 所有节次转为已取消
  await page.getByTestId('lv-cancel').first().click()
  await page.getByRole('button', { name: '确定' }).click()
  await expect(page.getByText('已销假').first()).toBeVisible()
  await expect(table.locator('tbody tr').first()).toContainText('已取消')
  // 颜色也要对:已取消不该和「待处理」长得一样,否则扫表时分不出还有几节没人处理
  const cancelledColor = await table.getByTestId('lv-status').first()
    .evaluate((el) => getComputedStyle(el).color)
  expect(cancelledColor).not.toBe(PENDING_ORANGE)
  await page.screenshot({ path: `${SHOTS}/leave-2-cancelled.png` })

  await deleteSemesterByYearTerm(page, YEAR, 1)
})

// ── 验收②:跨周末只展开上课日 + 半天假 ──
test('请假登记:跨周末只展开上课日;上午请假不含下午的课', async ({ page }) => {
  test.setTimeout(120_000)
  const YEAR = 139
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)
  const { sid, teacherId } = await seedPublishedSchool(page, YEAR)

  // 周三 ~ 下周一:中间夹周六日,王师只有周三有课
  const across = await post(page, `/api/leaves?semester_id=${sid}`, {
    teacher_id: teacherId, leave_type: 'official',
    start_date: WED, end_date: NEXT_MON,
  })
  expect(across.affected_count).toBe(5)
  expect([...new Set(across.affected_periods.map((p: { date: string }) => p.date))])
    .toEqual([WED])

  // 下周三上午:不该把下午的课列进来
  const half = await post(page, `/api/leaves?semester_id=${sid}`, {
    teacher_id: teacherId, leave_type: 'personal',
    start_date: WED2, end_date: WED2,
    start_time: '08:00', end_time: '12:00',
  })
  expect(half.affected_count).toBeGreaterThan(0)
  expect(half.affected_count).toBeLessThan(5)

  await page.goto('/leaves')
  await selectSemester(page, YEAR)
  await expect(page.getByTestId('lv-card')).toHaveCount(2)
  await expect(page.getByText(`${withWeekday(WED2)} 08:00~12:00`)).toBeVisible()
  const pendingColor = await page.getByTestId('lv-affected').first()
    .getByTestId('lv-status').first().evaluate((el) => getComputedStyle(el).color)
  expect(pendingColor).toBe(PENDING_ORANGE)
  await page.screenshot({ path: `${SHOTS}/leave-3-halfday.png` })

  await deleteSemesterByYearTerm(page, YEAR, 1)
})
