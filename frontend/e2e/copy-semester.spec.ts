import { expect, test } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

const SRC = 122
const DST = 123
const SHOTS = 'e2e/screenshots'

// 来源学期的起讫日;复制时应自动往后推半年带入默认值(M6-4)
const SRC_START = '2026-09-01'
const SRC_END = '2027-01-20'
const EXPECT_START = '2027-03-01'  // +6 个月
const EXPECT_END = '2027-07-20'

test('开新学期:复制到新学期,带起讫日与排课偏好设置', async ({ page }) => {
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })

  // 前置:清掉测试学期,建立来源学期(初中范本 → 含节次表+科目)
  await deleteSemesterByYearTerm(page, SRC, 1)
  await deleteSemesterByYearTerm(page, DST, 1)
  const src = await (await page.request.post('/api/semesters', {
    data: {
      academic_year: SRC, term: 1, template_key: 'junior_high',
      start_date: SRC_START, end_date: SRC_END,
    },
  })).json()

  // 来源学期调过排课偏好(每日同科上限 3、S2 权重 40)——这些不该在新学期悄悄回到默认值
  await page.request.put(`/api/solver/config?semester_id=${src.id}`, {
    data: { daily_subject_cap: 3, weights: { S2: 40 } },
  })

  await page.goto('/settings/semesters')
  const srcCard = page.locator('.n-card').filter({ hasText: `${SRC} 学年度第 1 学期` })
  await srcCard.getByTestId('copy-semester').first().click()

  // 对话框:目标学年度默认 +1;起讫日默认为来源往后推半年(组长只要确认校历再改)
  const start = page.getByTestId('copy-start').locator('input')
  const end = page.getByTestId('copy-end').locator('input')
  await expect(start).toHaveValue(EXPECT_START)
  await expect(end).toHaveValue(EXPECT_END)
  await page.screenshot({ path: `${SHOTS}/copy-1-dialog.png` })

  await page.getByTestId('copy-confirm').click()

  // 新学期出现于清单
  await expect(page.getByText(`${DST} 学年度第 1 学期`)).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/copy-2-list.png` })

  const list = await (await page.request.get('/api/semesters')).json()
  const dst = list.find((s: { academic_year: number; term: number }) =>
    s.academic_year === DST && s.term === 1)

  // 起讫日确实写进新学期(漏了它,请假展开与今日看板的判定会整个失准)
  expect(dst.start_date).toBe(EXPECT_START)
  expect(dst.end_date).toBe(EXPECT_END)

  // 排课偏好跟著走(先前会悄悄回到默认值,上学期调好的设置就白调了)
  const cfg = await (await page.request.get(
    `/api/solver/config?semester_id=${dst.id}`)).json()
  expect(cfg.daily_subject_cap).toBe(3)
  expect(cfg.weights.S2).toBe(40)

  const subjects = await (await page.request.get(`/api/subjects?semester_id=${dst.id}`)).json()
  expect(subjects.length).toBeGreaterThan(0)

  await deleteSemesterByYearTerm(page, SRC, 1)
  await deleteSemesterByYearTerm(page, DST, 1)
})
