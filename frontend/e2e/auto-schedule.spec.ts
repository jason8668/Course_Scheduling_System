import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

const SHOTS = 'e2e/screenshots'

const post = async (page: Page, url: string, data: object) =>
  (await page.request.post(url, { data })).json()

async function selectSemester(page: Page, year: number) {
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${year} 学年度第 1 学期` }).click()
}

/** 12 班初中:规模够大,solver 需要几秒收敛,才看得到进度与「提前结束」。 */
async function seedSchool(page: Page, sid: number) {
  const subjects: Record<string, number> = {}
  for (const s of await (await page.request.get(`/api/subjects?semester_id=${sid}`)).json()) {
    subjects[s.name] = s.id
  }
  const plan: [string, number, number][] = [
    ['国文', 5, 3], ['英语', 4, 3], ['数学', 4, 4], ['自然科学', 3, 2], ['社会', 3, 2],
    ['健康与体育', 3, 2], ['艺术', 3, 3], ['综合活动', 3, 2], ['科技', 2, 2], ['弹性学习', 3, 2],
  ]
  const teachers: Record<string, number[]> = {}
  for (const [subject, , count] of plan) {
    teachers[subject] = []
    for (let i = 0; i < count; i += 1) {
      const t = await post(page, `/api/teachers?semester_id=${sid}`,
        { name: `${subject}师${i + 1}`, base_periods: 20 })
      teachers[subject].push(t.id)
    }
  }
  const classes: number[] = []
  for (let i = 1; i <= 12; i += 1) {
    const c = await post(page, `/api/class-units?semester_id=${sid}`,
      { grade: 7, name: `70${i}`, track: 'junior_high' })
    classes.push(c.id)
  }
  for (const [subject, periods, count] of plan) {
    for (const [idx, cid] of classes.entries()) {
      await post(page, `/api/assignments?semester_id=${sid}`, {
        class_id: cid, subject_id: subjects[subject], periods_per_week: periods,
        teachers: [{ teacher_id: teachers[subject][idx % count] }], block_rules: [],
      })
    }
  }
}

// ── M3-4 验收①:启动 → 进度 → 提前结束 → 结果草稿 + 达成度报告 ──
test('自动排课:显示进度,提前结束取当前最佳解并产生新草稿', async ({ page }) => {
  test.setTimeout(180_000)
  const YEAR = 134
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })

  await deleteSemesterByYearTerm(page, YEAR, 1)
  const sem = await post(page, '/api/semesters',
    { academic_year: YEAR, term: 1, template_key: 'junior_high' })
  await seedSchool(page, sem.id)
  await post(page, `/api/timetables?semester_id=${sem.id}`, { name: '草稿A' })

  await page.goto('/scheduling/auto')
  await selectSemester(page, YEAR)

  // pre-flight 通过才会让人按下去
  await expect(page.getByText('资料检查通过,可以开始排课')).toBeVisible()
  await expect(page.getByText('12 班')).toBeVisible()

  await page.getByTestId('as-start').click()
  await expect(page.getByTestId('as-job')).toBeVisible()

  // 进度确实在跑:找到至少一个解之后「提前结束」才可按
  await expect(page.getByTestId('as-stop')).toBeEnabled({ timeout: 60_000 })
  await expect(page.getByTestId('as-solutions')).not.toHaveText('已找到 0 个解')
  await page.screenshot({ path: `${SHOTS}/auto-1-progress.png` })

  await page.getByTestId('as-stop').click()
  await expect(page.getByTestId('as-status')).toHaveText('已完成', { timeout: 60_000 })
  await expect(page.getByTestId('as-done')).toContainText('草稿A 自排结果')

  // 软约束达成度报告(人话明细)
  const report = page.getByTestId('as-report')
  await expect(report).toBeVisible()
  await expect(report).toContainText('同班同科目分散于不同日')
  await expect(report).toContainText('主科优先排上午')
  await page.waitForTimeout(300)
  await page.screenshot({ path: `${SHOTS}/auto-2-report.png` })

  // 结果写成新草稿(396 节),来源草稿完全没动
  const tts = await (await page.request.get(`/api/timetables?semester_id=${sem.id}`)).json()
  const source = tts.find((t: { name: string }) => t.name === '草稿A')
  const result = tts.find((t: { name: string }) => t.name === '草稿A 自排结果')
  expect(source.entry_count).toBe(0)
  expect(result.entry_count).toBe(396)
  expect(result.status).toBe('draft')

  await deleteSemesterByYearTerm(page, YEAR, 1)
})

// ── 验收③:pre-flight 挡下 + 失败时有明确讯息(而非永远转圈)──
test('自动排课:资料未通过前置检查时挡下,并列出待修正项目', async ({ page }) => {
  const YEAR = 135
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })

  await deleteSemesterByYearTerm(page, YEAR, 1)
  const sem = await post(page, '/api/semesters',
    { academic_year: YEAR, term: 1, template_key: 'junior_high' })
  const c = await post(page, `/api/class-units?semester_id=${sem.id}`,
    { grade: 3, name: '301', track: 'junior_high' })
  const s = await post(page, `/api/subjects?semester_id=${sem.id}`, { name: '国文X' })
  // base_periods 留 0(代表学校未维护基钟)才建得起这笔刻意超载的配课:
  // 有填基钟的教师会先被「超课时上限」挡在配课阶段,pre-flight 就没东西可检查了。
  const t = await post(page, `/api/teachers?semester_id=${sem.id}`,
    { name: '王师', base_periods: 0 })
  await post(page, `/api/assignments?semester_id=${sem.id}`, { // 40 节 > 35 可排节次
    class_id: c.id, subject_id: s.id, periods_per_week: 40,
    teachers: [{ teacher_id: t.id }], block_rules: [],
  })
  await post(page, `/api/timetables?semester_id=${sem.id}`, { name: '草稿A' })

  await page.goto('/scheduling/auto')
  await selectSemester(page, YEAR)

  await expect(page.getByTestId('pf-issue').first()).toContainText('超过可排节次')
  await page.getByTestId('as-start').click()

  await expect(page.getByTestId('as-blocking').first()).toContainText('301')
  await expect(page.getByTestId('as-job')).toHaveCount(0) // 没有进度卡 = 没有丢给 worker
  await page.screenshot({ path: `${SHOTS}/auto-3-blocked.png` })

  await deleteSemesterByYearTerm(page, YEAR, 1)
})

/** 301 班国文 12 节单节:每日上限 2 节 × 5 天 = 10 节 → 无解,但 pre-flight 看不出来。 */
async function seedInfeasible(page: Page, sid: number) {
  const c = await post(page, `/api/class-units?semester_id=${sid}`,
    { grade: 3, name: '301', track: 'junior_high' })
  const subjects: Record<string, number> = {}
  for (const s of await (await page.request.get(`/api/subjects?semester_id=${sid}`)).json()) {
    subjects[s.name] = s.id
  }
  const t = await post(page, `/api/teachers?semester_id=${sid}`, { name: '陈师', base_periods: 40 })
  await post(page, `/api/assignments?semester_id=${sid}`, {
    class_id: c.id, subject_id: subjects['国文'], periods_per_week: 12,
    teachers: [{ teacher_id: t.id }], block_rules: [],
  })
}

async function setupInfeasible(page: Page, year: number) {
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, year, 1)
  const sem = await post(page, '/api/semesters',
    { academic_year: year, term: 1, template_key: 'junior_high' })
  await seedInfeasible(page, sem.id)
  await post(page, `/api/timetables?semester_id=${sem.id}`, { name: '草稿A' })

  await page.goto('/scheduling/auto')
  await selectSemester(page, year)
  await expect(page.getByText('资料检查通过,可以开始排课')).toBeVisible()
  await page.getByTestId('as-minutes').locator('input').fill('1')
  return sem
}

// ── M3-5 验收①②:无解时说出是哪一件事、松开它就好 ──
test('无解时定位出原因并给出具体数字与建议', async ({ page }) => {
  test.setTimeout(240_000)
  const YEAR = 136
  const sem = await setupInfeasible(page, YEAR)

  await page.getByTestId('as-start').click()
  await expect(page.getByTestId('as-conflict')).toBeVisible({ timeout: 180_000 })

  // 不是「排不出来」,而是「12 节单节 > 每日 2 节 × 5 天 = 10 节」
  const conflict = page.getByTestId('as-conflict')
  await expect(conflict).toContainText('放宽其中任何一项即可排出课表')
  const cause = page.getByTestId('as-cause').first()
  await expect(cause).toContainText('301')
  await expect(cause).toContainText('12 节单节课')
  await expect(cause).toContainText('每日上限 2 节 × 5 天')
  await expect(cause).toContainText('建议:')

  // 一键照建议重试
  await expect(page.getByTestId('as-retry-partial')).toContainText('同班同科目每日节数上限')
  await conflict.scrollIntoViewIfNeeded()
  await page.screenshot({ path: `${SHOTS}/auto-4-conflict.png` })

  await deleteSemesterByYearTerm(page, YEAR, 1)
  expect(sem.id).toBeGreaterThan(0)
})

// ── M3-5 验收③:部分排课 → 大部分排入 + 未排清单 ──
test('部分排课排入大部分课务,并列出未排清单', async ({ page }) => {
  test.setTimeout(240_000)
  const YEAR = 137
  const sem = await setupInfeasible(page, YEAR)

  await page.getByTestId('as-partial').click()
  await page.getByTestId('as-start').click()

  await expect(page.getByTestId('as-status')).toHaveText('已完成', { timeout: 180_000 })
  await expect(page.getByTestId('as-done')).toContainText('草稿A 部分排课结果')

  // 排不下的 2 节列成清单,说得出是哪一班的哪一科
  const list = page.getByTestId('as-unscheduled')
  await expect(list).toBeVisible()
  await expect(list).toContainText('国文')
  await expect(list).toContainText('301')
  await expect(list).toContainText('2 节')
  await list.scrollIntoViewIfNeeded()
  await page.screenshot({ path: `${SHOTS}/auto-5-unscheduled.png` })

  // 12 节里排进去 10 节,来源草稿不动
  const tts = await (await page.request.get(`/api/timetables?semester_id=${sem.id}`)).json()
  expect(tts.find((t: { name: string }) => t.name === '草稿A').entry_count).toBe(0)
  expect(tts.find((t: { name: string }) => t.name === '草稿A 部分排课结果').entry_count).toBe(10)

  await deleteSemesterByYearTerm(page, YEAR, 1)
})
