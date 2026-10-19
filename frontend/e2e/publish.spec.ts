import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

const SHOTS = 'e2e/screenshots'
const XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const TEACHER_USER = 'e2e_teacher'
const TEACHER_PASS = 'e2eteacher1234'

const post = async (page: Page, url: string, data: object) =>
  (await page.request.post(url, { data })).json()
const get = async (page: Page, url: string) => (await page.request.get(url)).json()

async function selectSemester(page: Page, year: number) {
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${year} 学年度第 1 学期` }).click()
}

// ── M2-5 验收①②:多草稿并存、未排完发布警告、强制发布、旧版转封存 ──
test('版本与发布:未排完出现警告清单,确认后强制发布;发布新版旧版转封存', async ({ page }) => {
  const YEAR = 131
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })

  await deleteSemesterByYearTerm(page, YEAR, 1)
  const sem = await post(page, '/api/semesters', {
    academic_year: YEAR, term: 1, template_key: 'junior_high',
  })
  const sid = sem.id
  const c = await post(page, `/api/class-units?semester_id=${sid}`, { grade: 3, name: '301', track: 'junior_high' })
  const s = await post(page, `/api/subjects?semester_id=${sid}`, { name: '国文' })
  const t = await post(page, `/api/teachers?semester_id=${sid}`, { name: '王师' })
  const a = await post(page, `/api/assignments?semester_id=${sid}`, {
    class_id: c.id, subject_id: s.id, periods_per_week: 5,
    teachers: [{ teacher_id: t.id, is_lead: true }], block_rules: [],
  })

  await page.goto('/scheduling/versions')
  await selectSemester(page, YEAR)

  // 建立草稿A,只排 2/5 节(period_no 2 = 第一节)
  await page.getByTestId('v-new').click()
  await expect(page.getByTestId('v-status-草稿A')).toHaveText('草稿')
  const tts = await get(page, `/api/timetables?semester_id=${sid}`)
  const ttId = tts[0].id
  for (const wd of [1, 2]) {
    await page.request.post(`/api/timetables/${ttId}/entries`, {
      data: { course_assignment_id: a.id, weekday: wd, period_no: 2, span: 1 },
    })
  }
  await page.reload()
  await selectSemester(page, YEAR)

  // 检查课表:只是未排完时显示摘要,不开冲突清单
  await page.locator('[data-testid="v-row-草稿A"]').getByTestId('v-check').click()
  await expect(page.getByText('尚有 3 节未排')).toBeVisible()

  // 发布 → 警告清单(验收②)
  await page.locator('[data-testid="v-row-草稿A"]').getByTestId('v-publish').click()
  const unplaced = page.getByTestId('v-unplaced')
  await expect(unplaced).toBeVisible()
  await expect(unplaced).toContainText('国文')
  await expect(unplaced).toContainText('301')
  await page.waitForTimeout(350) // 等 modal 淡入完成,截图才清楚
  await page.screenshot({ path: `${SHOTS}/pub-1-warning.png` })

  // 确认后仍可强制发布
  await page.getByTestId('v-force-publish').click()
  await expect(page.getByTestId('v-status-草稿A')).toHaveText('已发布')
  await page.screenshot({ path: `${SHOTS}/pub-2-published.png` })

  // 复制为新草稿(验收①:两份并存)
  await page.locator('[data-testid="v-row-草稿A"]').getByTestId('v-duplicate').click()
  const copyRow = page.locator('[data-testid="v-row-草稿A 复本"]')
  await expect(copyRow).toBeVisible()
  await expect(page.getByTestId('v-status-草稿A 复本')).toHaveText('草稿')

  // 发布复本 → 原版转「已封存」
  await copyRow.getByTestId('v-publish').click()
  await page.getByTestId('v-force-publish').click()
  await expect(page.getByTestId('v-status-草稿A 复本')).toHaveText('已发布')
  await expect(page.getByTestId('v-status-草稿A')).toHaveText('已封存')
  await page.screenshot({ path: `${SHOTS}/pub-3-archived.png` })

  // 已发布为快照:格位不可再编辑
  const r = await page.request.post(`/api/timetables/${ttId}/entries`, {
    data: { course_assignment_id: a.id, weekday: 3, period_no: 2, span: 1 },
  })
  expect(r.status()).toBe(409)

  await deleteSemesterByYearTerm(page, YEAR, 1)
})

// ── M2-5 验收③:teacher 角色以手机浏览器查本人课表 ──
test.describe('教师端(手机)', () => {
  test.use({ viewport: { width: 390, height: 844 } }) // iPhone 尺寸

  test('teacher 角色登录手机浏览器,课表查询默认显示本人课表', async ({ page }) => {
    const YEAR = 132
    await login(page) // 先以教学组长建置资料
    await page.request.patch('/api/wizard/state', { data: { completed: true } })

    await deleteSemesterByYearTerm(page, YEAR, 1)
    const sem = await post(page, '/api/semesters', {
      academic_year: YEAR, term: 1, template_key: 'junior_high',
    })
    const sid = sem.id

    // 建立教师帐号:导入含「登录帐号」的教师范本(唯一能建立 teacher 帐号的途径)。
    // 帐号不随学期删除,故第二次执行改为建立教师并绑定既有帐号(保持幂等)。
    const file = fileURLToPath(new URL('./fixtures/teachers_with_account.xlsx', import.meta.url))
    const imp = await (await page.request.post(
      `/api/import/teachers?semester_id=${sid}&create_accounts=true`,
      { multipart: { file: { name: 't.xlsx', mimeType: XLSX, buffer: readFileSync(file) } } },
    )).json()

    let teacherId: number
    if (imp.imported === 1) {
      const list = await get(page, `/api/teachers?semester_id=${sid}`)
      teacherId = list.find((x: { name: string }) => x.name === '陈老师').id
    } else {
      const created = await post(page, `/api/teachers?semester_id=${sid}`, { name: '陈老师' })
      const accounts = await get(page, `/api/teachers/bindable-accounts?semester_id=${sid}`)
      const acc = accounts.find((x: { username: string }) => x.username === TEACHER_USER)
      expect(acc, '应可绑定既有的 e2e_teacher 帐号').toBeTruthy()
      await page.request.patch(`/api/teachers/${created.id}`, {
        data: { name: '陈老师', user_id: acc.id },
      })
      teacherId = created.id
    }

    // 陈老师的课,排入并发布(每周 1 节 → 排 1 节即完整,无需强制发布)
    const c = await post(page, `/api/class-units?semester_id=${sid}`, { grade: 7, name: '701', track: 'junior_high' })
    const s = await post(page, `/api/subjects?semester_id=${sid}`, { name: '公民' })
    const a = await post(page, `/api/assignments?semester_id=${sid}`, {
      class_id: c.id, subject_id: s.id, periods_per_week: 1,
      teachers: [{ teacher_id: teacherId, is_lead: true }], block_rules: [],
    })
    const tt = await post(page, `/api/timetables?semester_id=${sid}`, { name: '正式课表' })
    await page.request.post(`/api/timetables/${tt.id}/entries`, {
      data: { course_assignment_id: a.id, weekday: 3, period_no: 4, span: 1 },
    })
    const pubResp = await page.request.post(`/api/timetables/${tt.id}/publish`)
    expect(pubResp.status()).toBe(200)

    // 首登需改密码 → 以 API 一次设置为固定密码(非本卡验收重点);已改过则忽略
    await page.request.post('/api/auth/logout')
    const first = await page.request.post('/api/auth/login', {
      data: { username: TEACHER_USER, password: 'changeme' },
    })
    if (first.ok()) {
      await page.request.post('/api/auth/change-password', {
        data: { old_password: 'changeme', new_password: TEACHER_PASS },
      })
    }
    await page.request.post('/api/auth/logout')

    // ── 以教师身分登录(手机尺寸)──
    await login(page, TEACHER_USER, TEACHER_PASS)
    // 纯教师帐号一律导向课表查询
    await expect(page).toHaveURL(/\/timetable-query/)
    await expect(page.getByRole('heading', { name: '课表查询' })).toBeVisible()

    // 默认显示本人课表,且看得到自己的课
    await expect(page.getByText('本人课表')).toBeVisible()
    await expect(page.locator('[data-weekday="3"][data-period="4"]')).toContainText('公民')
    await expect(page.locator('[data-weekday="3"][data-period="4"]')).toContainText('701')

    // 教师看不到排课作业/基础资料等管理选单
    await expect(page.getByRole('link', { name: '课表查询' })).toBeVisible()
    await expect(page.getByText('排课作业')).toHaveCount(0)
    await expect(page.getByText('基础资料')).toHaveCount(0)
    await page.screenshot({ path: `${SHOTS}/pub-4-teacher-mobile.png` })

    // 唯读:格位不可拖曳
    await expect(page.locator('[data-weekday="3"][data-period="4"] .tg-card'))
      .toHaveAttribute('draggable', 'false')

    // 清理(以教学组长身分)
    await page.request.post('/api/auth/logout')
    await login(page)
    await deleteSemesterByYearTerm(page, YEAR, 1)
  })
})
