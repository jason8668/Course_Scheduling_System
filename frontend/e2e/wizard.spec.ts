import { expect, test } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

const YEAR = 120 // 使用不与既有资料冲突的学年度
const SHOTS = 'e2e/screenshots'

test('设置精灵:五步骤建立学期并于仪表板显示摘要', async ({ page }) => {
  await login(page)

  // 前置:重设精灵状态、清掉测试学期(含混合学制用的 121),确保从头跑且不受干扰
  await page.request.post('/api/wizard/reset')
  await deleteSemesterByYearTerm(page, YEAR, 1)
  await deleteSemesterByYearTerm(page, 121, 1)

  await page.goto('/wizard')
  await expect(page.getByRole('heading', { name: '设置精灵' })).toBeVisible()

  // Step 0:选初中范本
  await page.getByTestId('tpl-junior_high').click()
  await page.screenshot({ path: `${SHOTS}/wizard-1-template.png` })
  await page.getByTestId('wizard-next').click()

  // Step 1:设置学年度(改成 120 避免与既有 115 冲突)与起讫日期 → 建立学期
  const yearInput = page.getByTestId('wizard-year').locator('input')
  await yearInput.fill(String(YEAR))
  await yearInput.press('Enter')

  // 没填起讫日期不让过:少了它请假会被挡,而用户当下看不出哪里不对(#15)
  await page.getByTestId('wizard-next').click()
  await expect(page.getByText('请填学期起讫日期(请假与调代课需要)')).toBeVisible()

  const startInput = page.getByTestId('wizard-start').locator('input')
  await startInput.fill('2026-08-30')
  await startInput.press('Enter')
  const endInput = page.getByTestId('wizard-end').locator('input')
  await endInput.fill('2027-01-20')
  await endInput.press('Enter')
  await page.screenshot({ path: `${SHOTS}/wizard-2-year.png` })
  await page.getByTestId('wizard-next').click()

  // Step 2:建立学期后进入节次表步骤
  await expect(page.getByText('已依范本带入默认节次表')).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/wizard-3-periods.png` })
  await page.getByTestId('wizard-next').click()

  // Step 3:导入(略过)→ 下一步
  await page.screenshot({ path: `${SHOTS}/wizard-4-import.png` })
  await page.getByTestId('wizard-next').click()

  // Step 4:完成页应显示资料摘要
  await expect(page.getByText('初始设置即将完成')).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/wizard-5-done.png` })
  await page.getByTestId('wizard-finish').click()

  // 完成后导向基础资料页
  await expect(page.getByRole('heading', { name: '基础资料' })).toBeVisible()

  // 仪表板显示该学期摘要(验收①)
  await page.goto('/')
  await expect(page.getByText(`${YEAR} 学年度第 1 学期 · 资料摘要`)).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/wizard-6-dashboard.png` })

  // 清理:移除测试学期
  await deleteSemesterByYearTerm(page, YEAR, 1)
})
