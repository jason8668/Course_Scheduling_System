import { expect, test } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

const YEAR = 121 // 专用测试学年度
const SHOTS = 'e2e/screenshots'

// 完全中学情境:同学期两套节次表,班级可指定所属节次表。
test('混合学制:班级可指定节次表(≥2 套时出现下拉)', async ({ page }) => {
  await login(page)
  // 标记精灵已完成,避免首登守卫把导览转向 /wizard
  await page.request.patch('/api/wizard/state', { data: { completed: true } })

  // 前置(API):清掉测试学期后,建立含两套节次表的学期
  await deleteSemesterByYearTerm(page, 120, 1)
  await deleteSemesterByYearTerm(page, YEAR, 1)
  const semResp = await page.request.post('/api/semesters', {
    data: { academic_year: YEAR, term: 1, template_key: 'junior_high' },
  })
  const sem = await semResp.json()
  await page.request.post(`/api/semesters/${sem.id}/period-tables`, {
    data: { name: '高中部节次表', template_key: 'senior_high' },
  })

  // 进入基础资料 → 选该学期 → 班级分页
  await page.goto('/basedata')
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${YEAR} 学年度第 1 学期` }).click()
  await page.locator('.n-tabs-tab', { hasText: '班级' }).click()

  // 新增班级:节次表下拉应出现(因有 2 套)
  await page.getByTestId('class-add').click()
  await page.getByTestId('class-name').locator('input').fill('高中501')
  const ptSelect = page.getByTestId('class-period-table')
  await expect(ptSelect).toBeVisible()
  await ptSelect.click()
  await page.locator('.n-base-select-option', { hasText: '高中部节次表' }).click()
  await page.screenshot({ path: `${SHOTS}/mixed-1-form.png` })
  await page.getByTestId('class-save').click()

  // 列表应出现该班,且节次表栏显示「高中部节次表」
  await expect(page.getByRole('cell', { name: '高中501' })).toBeVisible()
  await expect(page.getByRole('cell', { name: '高中部节次表' })).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/mixed-2-list.png` })

  // 清理
  await deleteSemesterByYearTerm(page, YEAR, 1)
})
