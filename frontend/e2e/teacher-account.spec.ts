import { expect, test } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

const YEAR = 124 // 专用测试学年度
const SHOTS = 'e2e/screenshots'

// M2-0:教师表单新增联络信息(Email/手机/LINE)与帐号绑定栏位。
test('教师联络信息:新增教师填入 Email/手机/LINE 并保存', async ({ page }) => {
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })

  // 前置(API):建立干净的测试学期
  await deleteSemesterByYearTerm(page, YEAR, 1)
  await page.request.post('/api/semesters', {
    data: { academic_year: YEAR, term: 1, template_key: 'junior_high' },
  })

  // 进入基础资料 → 选该学期 → 教师分页
  await page.goto('/basedata')
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${YEAR} 学年度第 1 学期` }).click()
  await page.locator('.n-tabs-tab', { hasText: '教师' }).click()

  // 新增教师,填入姓名与联络信息
  await page.getByTestId('teacher-add').click()
  await page.getByTestId('teacher-name').locator('input').fill('陈老师')
  await page.getByTestId('teacher-email').locator('input').fill('chen@example.edu.tw')
  // 帐号绑定下拉存在(本学期尚无教师帐号时为空清单,栏位仍应可见)
  await expect(page.getByTestId('teacher-account')).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/teacher-1-form.png` })
  await page.getByTestId('teacher-save').click()

  // 列表出现该教师
  await expect(page.getByRole('cell', { name: '陈老师' })).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/teacher-2-list.png` })

  // 验证 Email 已保存(经 API 确认)
  const list = await (await page.request.get('/api/semesters')).json()
  const sem = list.find((s: { academic_year: number; term: number }) =>
    s.academic_year === YEAR && s.term === 1)
  const teachers = await (await page.request.get(`/api/teachers?semester_id=${sem.id}`)).json()
  const chen = teachers.find((t: { name: string }) => t.name === '陈老师')
  expect(chen.email).toBe('chen@example.edu.tw')

  // 清理
  await deleteSemesterByYearTerm(page, YEAR, 1)
})

/**
 * #9:导入时没建帐号的老师,事后要能直接补一个。
 * 先前帐号只能在 Excel 导入时勾选建立,重新导入同一位老师又会被重复检查挡下,
 * 于是那位老师永远拿不到帐号。顺便验 #10 回复里答应的「重设密码」。
 */
test('教师帐号:事后补开登录帐号,可登录;重设密码后旧密码失效', async ({ page }) => {
  test.setTimeout(120_000)
  const PW = 'teacherpw1234'
  const NEW_PW = 'teacherpw5678'
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })

  await deleteSemesterByYearTerm(page, YEAR, 1)
  const sem = await (await page.request.post('/api/semesters', {
    data: { academic_year: YEAR, term: 1, template_key: 'junior_high' },
  })).json()
  const username = `e2e_late_${Date.now()}`

  await page.goto('/basedata')
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${YEAR} 学年度第 1 学期` }).click()
  await page.locator('.n-tabs-tab', { hasText: '教师' }).click()

  // 先建一位没有帐号的老师(模拟导入时没勾「建立帐号」)
  await page.getByTestId('teacher-add').click()
  await page.getByTestId('teacher-name').locator('input').fill('林老师')
  await page.getByTestId('teacher-save').click()
  await expect(page.getByRole('cell', { name: '林老师' })).toBeVisible()

  // 编辑 → 补开帐号
  await page.getByRole('row', { name: /林老师/ }).getByTestId('teacher-edit').click()
  await page.getByTestId('teacher-new-username').locator('input').fill(username)
  await page.getByTestId('teacher-new-password').locator('input').fill(PW)
  await page.getByTestId('teacher-create-account').click()
  await expect(page.getByText(/已建立帐号/)).toBeVisible()
  // 建好即绑定,界面改成显示帐号与重设密码
  await expect(page.getByTestId('teacher-reset-submit')).toBeVisible()

  const teachers = await (await page.request.get(`/api/teachers?semester_id=${sem.id}`)).json()
  const lin = teachers.find((t: { name: string }) => t.name === '林老师')
  expect(lin.user_id, '补开的帐号要自动绑定这位老师').toBeTruthy()

  // 重设密码 → 旧密码失效、新密码可用
  await page.getByTestId('teacher-reset-password').locator('input').fill(NEW_PW)
  await page.getByTestId('teacher-reset-submit').click()
  await page.getByRole('button', { name: '确定' }).click()
  await expect(page.getByText(/密码已重设/)).toBeVisible()

  // 以下改用 API 验证登录(会换掉目前的登录身分,所以放在 UI 操作之后)
  await page.request.post('/api/auth/logout')
  const bad = await page.request.post('/api/auth/login', {
    data: { username, password: PW }, failOnStatusCode: false,
  })
  expect(bad.status(), '重设后旧密码应该失效').toBe(401)
  const good = await page.request.post('/api/auth/login', {
    data: { username, password: NEW_PW },
  })
  expect(good.ok(), '新密码应该可以登录').toBeTruthy()
  expect((await good.json()).must_change_password, '重设后对方下次登录须自行改密码').toBe(true)

  // 清理(换回组长身分)
  await page.request.post('/api/auth/logout')
  await login(page)
  await deleteSemesterByYearTerm(page, YEAR, 1)
})

/**
 * #19:离职教师的处理。先前删除教师会连带删掉请假纪录,却不会停用其登录帐号
 * (`users.is_active` 有栏位、登录会检查,但没有任何地方设置得了)。
 */
test('教师帐号:可停用与重新启用;删除教师时帐号一并停用', async ({ page }) => {
  test.setTimeout(120_000)
  const PW = 'disablepw1234'
const YEAR_DISABLE = 155  // 专用学年度:避免与其他 spec 互删学期
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })

  await deleteSemesterByYearTerm(page, YEAR_DISABLE, 1)
  await page.request.post('/api/semesters', {
    data: { academic_year: YEAR_DISABLE, term: 1, template_key: 'junior_high' },
  })
  const username = `e2e_leave_${Date.now()}`

  await page.goto('/basedata')
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${YEAR_DISABLE} 学年度第 1 学期` }).click()
  await page.locator('.n-tabs-tab', { hasText: '教师' }).click()

  await page.getByTestId('teacher-add').click()
  await page.getByTestId('teacher-name').locator('input').fill('张老师')
  await page.getByTestId('teacher-save').click()
  await expect(page.getByRole('cell', { name: '张老师' })).toBeVisible()

  const row = page.getByRole('row', { name: /张老师/ })
  await row.getByTestId('teacher-edit').click()
  await page.getByTestId('teacher-new-username').locator('input').fill(username)
  await page.getByTestId('teacher-new-password').locator('input').fill(PW)
  await page.getByTestId('teacher-create-account').click()
  await expect(page.getByTestId('teacher-account-state')).toContainText('可登录')

  // 停用 → 立刻登不进来
  await page.getByTestId('teacher-account-toggle').click()
  await expect(page.getByTestId('teacher-account-state')).toContainText('已停用')
  const blocked = await page.request.post('/api/auth/login', {
    data: { username, password: PW }, failOnStatusCode: false,
  })
  expect(blocked.status(), '停用后应该登不进来').toBe(403)

  // 重新启用 → 又可以登录
  await page.getByTestId('teacher-account-toggle').click()
  await expect(page.getByTestId('teacher-account-state')).toContainText('可登录')
  const ok = await page.request.post('/api/auth/login', {
    data: { username, password: PW }, failOnStatusCode: false,
  })
  expect(ok.status(), '重新启用后应该可以登录').toBe(200)
  await page.request.post('/api/auth/logout')
  await login(page)

  // 删除教师:确认框要先讲后果,删除后帐号一并停用
  await page.goto('/basedata')
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${YEAR_DISABLE} 学年度第 1 学期` }).click()
  await page.locator('.n-tabs-tab', { hasText: '教师' }).click()
  await page.getByRole('row', { name: /张老师/ }).getByTestId('teacher-delete').click()
  const confirm = page.getByTestId('teacher-delete-confirm')
  await expect(confirm).toContainText('停用')
  await expect(confirm).toContainText('离职')
  await page.getByRole('button', { name: '确定' }).click()
  await expect(page.getByText('已删除')).toBeVisible()

  const afterDelete = await page.request.post('/api/auth/login', {
    data: { username, password: PW }, failOnStatusCode: false,
  })
  expect(afterDelete.status(), '教师删除后帐号不该还能登录').toBe(403)

  // 这里仍是组长的登录状态(上面失败的登录不会换掉 session),直接清掉测试学期
  await deleteSemesterByYearTerm(page, YEAR_DISABLE, 1)
})
