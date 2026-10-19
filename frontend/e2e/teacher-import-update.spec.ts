import { expect, test } from '@playwright/test'
import { fileURLToPath } from 'node:url'
import { deleteSemesterByYearTerm, login } from './helpers'

/**
 * #18:每学年职务异动(卸任/新任行政职、课时与减课调整)要改几十位老师,
 * 但导入教师遇到既有教师只会报「重复」、整批不写入,只能一位位手改。
 * 勾选「既有教师改为更新资料」后,既有的改为更新、新的照旧新增。
 */
const YEAR = 154
const SHOTS = 'e2e/screenshots'

test('导入教师:勾选更新后,既有教师改为更新资料,空白栏位保留原值', async ({ page }) => {
  test.setTimeout(120_000)
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)

  const post = async (url: string, data: object) => (await page.request.post(url, { data })).json()
  const sem = await post('/api/semesters', {
    academic_year: YEAR, term: 1, template_key: 'junior_high',
  })
  const sid = sem.id
  const subjects = await (await page.request.get(`/api/subjects?semester_id=${sid}`)).json()
  const math = subjects.find((s: { name: string }) => s.name === '数学')
    ?? await post(`/api/subjects?semester_id=${sid}`, { name: '数学' })
  if (!subjects.some((s: { name: string }) => s.name === '物理')) {
    await post(`/api/subjects?semester_id=${sid}`, { name: '物理' })
  }

  // 既有教师:教学组长、课时 20、减课 4、教数学、有 Email
  const before = await post(`/api/teachers?semester_id=${sid}`, {
    name: '王小明', id_last4: '1234', base_periods: 20, admin_title: '教学组长',
    admin_reduction: 4, subject_ids: [math.id], email: 'wang@example.edu.tw',
  })

  await page.goto('/basedata')
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${YEAR} 学年度第 1 学期` }).click()
  await page.locator('.n-tabs-tab', { hasText: '批次导入' }).click()
  await page.locator('.n-radio-button', { hasText: '教师' }).click()

  const file = fileURLToPath(new URL('./fixtures/teachers_update.xlsx', import.meta.url))
  await page.locator('input[type="file"]').setInputFiles(file)

  // 没勾更新 → 既有教师被判重复,整批不写入
  await page.getByRole('button', { name: '开始导入' }).click()
  await expect(page.getByText(/重复/)).toBeVisible()
  expect(await (await page.request.get(`/api/teachers?semester_id=${sid}`)).json())
    .toHaveLength(1)

  // 勾选更新后再导入一次
  await page.getByTestId('import-update').click()
  await page.locator('input[type="file"]').setInputFiles(file)
  await page.getByRole('button', { name: '开始导入' }).click()
  await expect(page.getByTestId('import-ok')).toContainText('新增 1 笔、更新 1 笔')
  await page.screenshot({ path: `${SHOTS}/import-teacher-update.png` })

  const teachers = await (await page.request.get(`/api/teachers?semester_id=${sid}`)).json()
  expect(teachers).toHaveLength(2)
  const wang = teachers.find((t: { name: string }) => t.name === '王小明')
  expect(wang.id, '应该是更新同一笔,不是新建').toBe(before.id)
  expect(wang.admin_title ?? '', '行政职称填「无」= 卸任').toBe('')
  expect(wang.base_periods).toBe(22)
  expect(wang.admin_reduction).toBe(0)
  expect(wang.subjects.map((s: { name: string }) => s.name).sort()).toEqual(['数学', '物理'].sort())
  expect(wang.email, '空白栏位要保留原值').toBe('wang@example.edu.tw')

  await deleteSemesterByYearTerm(page, YEAR, 1)
})
