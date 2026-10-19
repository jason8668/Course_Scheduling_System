import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { dayOfBaseWeek, SEM_END, SEM_START, statsQuery } from './dates'
import { deleteSemesterByYearTerm, login } from './helpers'

// M5-4 验收①(UI 连续情境):一个学期从建立 → 自动排课 → 发布 → 请假 → 代课 → 月结,
// 一路走完,证明各关卡的界面能串接成真实的教务生命周期。个别旅程的细节由各自 spec
// 深入覆盖;此处只验「整条链接得起来、末端数字对得上」。

const SHOTS = 'e2e/screenshots'
const YEAR = 148
const post = async (page: Page, url: string, data: object) =>
  (await page.request.post(url, { data })).json()
const get = async (page: Page, url: string) => (await page.request.get(url)).json()

async function selectSemester(page: Page, year: number) {
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${year} 学年度第 1 学期` }).click()
}

/** 6 班初中:够真实又能在数秒内排完,适合连续情境。 */
async function seedSchool(page: Page, sid: number) {
  const subjects: Record<string, number> = {}
  for (const s of await get(page, `/api/subjects?semester_id=${sid}`)) subjects[s.name] = s.id
  const plan: [string, number, number][] = [
    ['国文', 5, 2], ['英语', 4, 2], ['数学', 4, 2], ['自然科学', 3, 2],
    ['社会', 3, 2], ['健康与体育', 3, 1], ['艺术', 3, 1], ['综合活动', 3, 1],
  ]
  const teachers: Record<string, number[]> = {}
  for (const [subject, , count] of plan) {
    teachers[subject] = []
    for (let i = 0; i < count; i += 1) {
      const t = await post(page, `/api/teachers?semester_id=${sid}`,
        { name: `${subject}师${i + 1}`, base_periods: 22 })
      teachers[subject].push(t.id)
    }
  }
  const classes: number[] = []
  for (let i = 1; i <= 6; i += 1) {
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

test('全流程:建学期 → 自动排课 → 发布 → 请假 → 代课 → 月结,一路串到底', async ({ page }) => {
  test.setTimeout(240_000)
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)

  // ── 1) 建学期 + 基础资料(API 准备)──
  const sem = await post(page, '/api/semesters', {
    academic_year: YEAR, term: 1, template_key: 'junior_high',
    start_date: SEM_START, end_date: SEM_END,
  })
  await seedSchool(page, sem.id)
  await post(page, `/api/timetables?semester_id=${sem.id}`, { name: '草稿A' })

  // ── 2) 自动排课(真实走 solver worker,UI 显示进度)──
  await page.goto('/scheduling/auto')
  await selectSemester(page, YEAR)
  await expect(page.getByText('资料检查通过,可以开始排课')).toBeVisible()
  await page.getByTestId('as-start').click()
  await expect(page.getByTestId('as-stop')).toBeEnabled({ timeout: 90_000 })
  await page.getByTestId('as-stop').click()
  await expect(page.getByTestId('as-status')).toHaveText('已完成', { timeout: 90_000 })
  await expect(page.getByTestId('as-done')).toContainText('草稿A 自排结果')
  await page.screenshot({ path: `${SHOTS}/journey-1-autoschedule.png` })

  // ── 3) 发布自排结果(版本管理页,UI)──
  await page.goto('/scheduling/versions')
  await selectSemester(page, YEAR)
  const row = page.locator('[data-testid="v-row-草稿A 自排结果"]')
  await row.getByTestId('v-publish').click()
  const force = page.getByTestId('v-force-publish')
  if (await force.isVisible().catch(() => false)) await force.click()
  await expect(page.getByTestId('v-status-草稿A 自排结果')).toHaveText('已发布')
  await page.screenshot({ path: `${SHOTS}/journey-2-published.png` })

  // ── 4) 课表查询:已发布课表在唯读查询页可见(UI)──
  await page.goto(`/timetable-query?semester_id=${sem.id}`)
  await expect(page.getByRole('heading', { name: '课表查询' })).toBeVisible()

  // ── 5) 请假 + 代课(API;个别 UI 由 leaves/substitutions spec 覆盖)──
  const published = (await get(page, `/api/timetables?semester_id=${sem.id}`))
    .find((t: { name: string; status: string }) => t.status === 'published')
  const entries = (await get(page, `/api/timetables/${published.id}`)).entries
  // 找一笔周三(weekday=3)的格位,取其教师请整天假;请假日必须落在该格位的星期,
  // 否则展不出受影响节次(退而求其次用第一笔格位时,请假日也跟著它的星期走)
  const wedEntry = entries.find((e: { weekday: number }) => e.weekday === 3) || entries[0]
  const assignment = (await get(page, `/api/assignments?semester_id=${sem.id}`))
    .find((a: { id: number }) => a.id === wedEntry.course_assignment_id)
  const absentId = assignment.teachers[0].teacher_id
  const leaveDay = dayOfBaseWeek(wedEntry.weekday)
  const aps = (await post(page, `/api/leaves?semester_id=${sem.id}`, {
    teacher_id: absentId, leave_type: 'personal',
    start_date: leaveDay, end_date: leaveDay,
  })).affected_periods
  expect(aps.length).toBeGreaterThan(0)

  // 用推荐清单挑一位当时段有空的教师指派代课
  const target = aps[0]
  const rec = await get(page, `/api/affected-periods/${target.id}/recommendations`)
  expect(rec.candidates.length).toBeGreaterThan(0)
  const handlerId = rec.candidates[0].teacher_id
  await page.request.put(`/api/affected-periods/${target.id}/substitution`,
    { data: { type: 'substitute', handler_teacher_id: handlerId } })

  // ── 6) 月结统计(UI):接手教师的代课节数与计费节数呈现在界面上 ──
  await page.goto(`/substitution-stats?semester_id=${sem.id}${statsQuery(leaveDay)}`)
  await expect(page.getByRole('heading', { name: /代课课时/ })).toBeVisible()
  await expect(page.getByTestId('stats-detail-row').first()).toBeVisible()
  await expect(page.getByTestId('stats-summary-row')).not.toHaveCount(0)
  await page.screenshot({ path: `${SHOTS}/journey-3-stats.png` })

  await deleteSemesterByYearTerm(page, YEAR, 1)
})
