import { expect, test } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

/**
 * 「学期与节次表」的三个视窗(编辑学期、新增节次表、复制到新学期)关不掉:
 * X、Esc、点视窗外都没反应,只能重新整理(用户回报)。
 *
 * 原因:视窗原本放在 n-space 里,和 v-for 产生的学期卡片同一层。n-space 会把每个子节点
 * 包一层没有 key 的 div,学期清单载入后卡片数量一变,视窗就跟著换位置重挂。
 * **只有正式建置会坏、开发模式正常**,所以单元测试看不出来——这支测试跑的是 Docker 里的正式建置。
 */
const YEAR = 157

test('学期与节次表:三个视窗都能用 X、Esc、点视窗外关闭', async ({ page }) => {
  test.setTimeout(120_000)
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)
  await page.request.post('/api/semesters', {
    data: {
      academic_year: YEAR, term: 1, template_key: 'junior_high',
      start_date: '2026-08-31', end_date: '2027-01-20',
    },
  })

  try {
    await page.goto('/settings/semesters')
    const card = page.locator('.n-card', { hasText: `${YEAR} 学年度第 1 学期` }).first()
    const modal = page.locator('.n-modal')
    const openers: [string, () => Promise<void>][] = [
      ['编辑学期', () => card.getByTestId('sem-edit').click()],
      ['新增节次表', () => card.getByRole('button', { name: /新增节次表/ }).click()],
      ['复制到新学期', () => card.getByTestId('copy-semester').click()],
    ]
    const closers: [string, () => Promise<void>][] = [
      ['X', () => page.locator('.n-modal .n-base-close').click()],
      ['Esc', () => page.keyboard.press('Escape')],
      ['点视窗外', () => page.mouse.click(15, 500)],
    ]
    for (const [name, open] of openers) {
      for (const [how, close] of closers) {
        await open()
        await expect(modal, `${name} 应该打得开`).toBeVisible()
        await close()
        await expect(modal, `${name} 用「${how}」关不掉`).toBeHidden()
      }
    }
  } finally {
    await deleteSemesterByYearTerm(page, YEAR, 1)
  }
})
