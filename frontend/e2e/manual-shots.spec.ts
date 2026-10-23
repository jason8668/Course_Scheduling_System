import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { iso, onOrAfter } from './dates'

// 操作手册补图产生器(不是验收测试,CI 不跑)。对示范站逐页截图 → docs/manual-img/。
//
// 重拍全部 14 张(整套流程约 1 分钟):
//   1) 起一套**全新**的栈(空资料库),.env 设 ADMIN_PASSWORD=DemoSetup2026!,例如
//        docker compose -p manual --env-file <你的.env> up -d
//   2) E2E_BASE_URL=http://localhost:<port> npm run e2e:manual
//
// 两支测试对站台状态的要求不同,故分开(执行顺序即档案顺序,workers=1):
//   01–02:需**精灵尚未完成**的全新站台。
//   03–14:自己把示范资料备齐(幂等),再逐页截图。
//
// 示范资料与改密都刻意做在这支 spec 里、不靠外部脚本:上一次是临时手动灌的,
// 结果要重拍时没人知道当初的资料长什么样子,只好整套重猜一遍。

const SHOTS = '../docs/manual-img'
const ADMIN = 'admin'
const INIT_PW = 'DemoSetup2026!' // .env 的 ADMIN_PASSWORD(首次登录会被强制改密)
const PW = 'DemoManual2026!'     // 本 spec 首次执行时改成这个,之后沿用
const YEAR = 115
const TERM = 1

test.use({
  baseURL: process.env.E2E_BASE_URL || 'http://localhost:8081',
  viewport: { width: 1440, height: 900 },
})

const post = async (p: Page, url: string, data: object) => (await p.request.post(url, { data })).json()
const get = async (p: Page, url: string) => (await p.request.get(url)).json()

/** 登录示范站;全新站台的 admin 会被要求改密(路由守卫会把每一页导去改密页),这里一并处理掉。 */
async function loginAsAdmin(page: Page) {
  const r = await page.request.post('/api/auth/login', { data: { username: ADMIN, password: PW } })
  if (r.ok()) return

  const first = await page.request.post('/api/auth/login',
    { data: { username: ADMIN, password: INIT_PW } })
  expect(first.ok(), `admin 密码不是 ${PW} 也不是 ${INIT_PW};请以空资料库重起示范站`).toBeTruthy()
  const changed = await page.request.post('/api/auth/change-password',
    { data: { old_password: INIT_PW, new_password: PW } })
  expect(changed.ok(), '首次登录改密失败').toBeTruthy()
}

/** 示范站学期内、今日之后的第一个周三(代课不能指派已上过的节次,故不可取过去的日子)。 */
async function pickLeaveDay(page: Page, sid: number): Promise<string> {
  const sem = await get(page, `/api/semesters/${sid}`)
  const earliest = new Date()
  earliest.setDate(earliest.getDate() + 1)
  const start = new Date(sem.start_date)
  const from = start > earliest ? start : earliest
  const wed = onOrAfter(3, from)
  if (iso(wed) > sem.end_date) {
    throw new Error(`示范学期(${sem.start_date}~${sem.end_date})已过期,请以空资料库重跑`)
  }
  return iso(wed)
}

async function selectSemester(page: Page) {
  const sel = page.locator('.n-base-selection').first()
  if (await sel.isVisible().catch(() => false)) {
    await sel.click()
    const opt = page.locator('.n-base-select-option', { hasText: `${YEAR} 学年度第 ${TERM} 学期` })
    if (await opt.first().isVisible().catch(() => false)) await opt.first().click()
    else await page.keyboard.press('Escape')
  }
  await page.waitForLoadState('networkidle')
}

/** 示范学校:初中 3 班、8 位教师、24 笔配课(幂等:已存在就直接沿用)。 */
async function ensureDemoData(page: Page): Promise<number> {
  const found = (await get(page, '/api/semesters'))
    .find((s: { academic_year: number; term: number }) => s.academic_year === YEAR && s.term === TERM)
  if (found) return found.id

  // 学期起讫取「今天往后推一周」起算的半年,截图才不会因为日期过期而失效
  const start = new Date()
  start.setDate(start.getDate() + 7)
  const end = new Date(start)
  end.setMonth(end.getMonth() + 5)
  const sem = await post(page, '/api/semesters', {
    academic_year: YEAR, term: TERM, template_key: 'junior_high',
    start_date: iso(start), end_date: iso(end),
  })
  const sid = sem.id as number

  const subjects: Record<string, number> = {}
  for (const s of await get(page, `/api/subjects?semester_id=${sid}`)) subjects[s.name] = s.id

  // 王大明是手册里请假的那位(07/08 两张图靠他)
  const TEACHERS: [string, string[]][] = [
    ['王大明', ['国文']], ['李淑芬', ['国文']],
    ['陈志明', ['数学']], ['林美惠', ['数学']],
    ['张文华', ['英语']], ['黄建宏', ['自然科学']],
    ['吴雅玲', ['社会', '综合活动']], ['刘俊杰', ['健康与体育', '艺术']],
  ]
  const tid: Record<string, number> = {}
  for (const [name, subs] of TEACHERS) {
    const t = await post(page, `/api/teachers?semester_id=${sid}`, {
      name, base_periods: 0, subject_ids: subs.map((s) => subjects[s]).filter(Boolean),
    })
    tid[name] = t.id
  }

  const classes: number[] = []
  for (const name of ['701', '702', '703']) {
    const c = await post(page, `/api/class-units?semester_id=${sid}`,
      { grade: 7, name, track: 'junior_high', student_count: 28 })
    classes.push(c.id)
  }

  const PLAN: [string, number, string[]][] = [
    ['国文', 5, ['王大明', '李淑芬']], ['数学', 4, ['陈志明', '林美惠']],
    ['英语', 4, ['张文华']], ['自然科学', 3, ['黄建宏']], ['社会', 3, ['吴雅玲']],
    ['健康与体育', 2, ['刘俊杰']], ['艺术', 2, ['刘俊杰']], ['综合活动', 2, ['吴雅玲']],
  ]
  const load: Record<string, number> = {}
  for (const [i, cid] of classes.entries()) {
    for (const [subj, periods, pool] of PLAN) {
      if (!subjects[subj]) continue
      const name = pool[i % pool.length]
      await post(page, `/api/assignments?semester_id=${sid}`, {
        class_id: cid, subject_id: subjects[subj], periods_per_week: periods,
        teachers: [{ teacher_id: tid[name] }], block_rules: [],
      })
      load[name] = (load[name] ?? 0) + periods
    }
  }

  // 应授节数对齐实际配课量:否则课时表整排红字「不足」,手册看起来像系统在报错
  for (const t of await get(page, `/api/teachers?semester_id=${sid}`)) {
    await page.request.patch(`/api/teachers/${t.id}`, {
      data: {
        name: t.name, base_periods: load[t.name] ?? 0,
        subject_ids: (t.subjects ?? []).map((s: { id: number }) => s.id),
        admin_reduction: 0, is_external: false,
      },
    })
  }
  return sid
}

/**
 * 把默认草稿(草稿A)排到一半:701 的国文与数学各就各位,其余留在「未排课务」。
 * 手册的手动排课章节要呈现的正是这个状态——格子里有课、右侧还有待排的卡片。
 */
async function seedHalfScheduledDraft(page: Page, sid: number) {
  // 「草稿A」是排课工作台首次载入时才自动建立的;这里抢在它前面,所以得自己建。
  const drafts = await get(page, `/api/timetables?semester_id=${sid}`)
  const draft = drafts.find((t: { name: string }) => t.name === '草稿A')
    ?? await post(page, `/api/timetables?semester_id=${sid}`, { name: '草稿A' })
  const full = await get(page, `/api/timetables/${draft.id}`)
  if ((full.entries ?? []).length) return // 已排过就不再动(幂等)

  const classes = await get(page, `/api/class-units?semester_id=${sid}`)
  const c701 = classes.find((c: { name: string }) => c.name === '701')
  const periods = (await get(page, `/api/class-units/${c701.id}/period-table`)).periods
    .filter((p: { type: string }) => p.type === 'regular')
  // 配课的班级在 scheduling_unit.classes、科目在 subject(不是扁平的 class_id/subject_name)
  const assignments = (await get(page, `/api/assignments?semester_id=${sid}`)).filter(
    (a: { scheduling_unit: { classes: { id: number }[] } }) =>
      a.scheduling_unit.classes.some((c) => c.id === c701.id),
  )

  // 国文 5 节排周一~周五第一节;数学 4 节排周一~周四第二节
  const place = async (subject: string, slotIndex: number, days: number[]) => {
    const a = assignments.find((x: { subject: { name: string } }) => x.subject.name === subject)
    if (!a) return
    for (const weekday of days) {
      const target = periods.filter((x: { weekday: number }) => x.weekday === weekday)[slotIndex]
      if (!target) continue
      await page.request.post(`/api/timetables/${draft.id}/entries`, {
        data: {
          course_assignment_id: a.id, weekday, period_no: target.period_no, span: 1,
        },
      })
    }
  }
  await place('国文', 0, [1, 2, 3, 4, 5])
  await place('数学', 1, [1, 2, 3, 4])
}

test('产生操作手册截图(01–02,需全新未设置站台)', async ({ page }) => {
  // ── 01 登录页 ──
  await page.goto('/login')
  await expect(page.getByRole('button', { name: '登录' })).toBeVisible({ timeout: 20_000 })
  await page.waitForTimeout(500)
  await page.screenshot({ path: `${SHOTS}/01-login.png` })

  // ── 02 设置精灵(第一步:选学制范本)──
  await loginAsAdmin(page)
  await page.goto('/wizard')
  await expect(page.getByRole('heading', { name: '设置精灵' })).toBeVisible({ timeout: 20_000 })
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${SHOTS}/02-wizard.png` })
})

test('产生操作手册截图(03–14)', async ({ page }) => {
  test.setTimeout(300_000)

  await loginAsAdmin(page)
  const sid = await ensureDemoData(page)
  // 精灵标记完成,否则路由守卫会把每一页导回精灵
  await page.request.patch('/api/wizard/state', { data: { completed: true } })

  // ── 03 配课管理 ──
  await page.goto('/scheduling/assignments')
  await selectSemester(page)
  await expect(page.getByRole('heading', { name: '配课管理' })).toBeVisible({ timeout: 20_000 })
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${SHOTS}/03-assignments.png` })

  // ── 04 排课工作台(排到一半的状态:手册要讲的是拖拉排课,空白课表讲不了故事)──
  await seedHalfScheduledDraft(page, sid)
  await page.goto('/scheduling/workbench')
  await selectSemester(page)
  await page.waitForTimeout(1200)
  await page.screenshot({ path: `${SHOTS}/04-workbench.png` })

  // ── 05 自动排课(真的跑一次,截进度与达成度报告)──
  await page.goto('/scheduling/auto')
  await selectSemester(page)
  const done = page.getByTestId('as-status')
  if (!(await done.isVisible().catch(() => false))) {
    await expect(page.getByText('资料检查通过,可以开始排课')).toBeVisible({ timeout: 30_000 })
    await page.getByTestId('as-start').click()
    // 3 班的示范学校数秒即解完,等它自己完成即可
    await expect(done).toHaveText('已完成', { timeout: 180_000 })
  }
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${SHOTS}/05-auto-schedule.png` })

  // ── 06 版本与发布(把自排结果发布出去)──
  await page.goto('/scheduling/versions')
  await selectSemester(page)
  const autoRow = page.locator('tr', { hasText: '自排结果' }).first()
  await expect(autoRow).toBeVisible({ timeout: 20_000 })
  if (!(await page.locator('tr', { hasText: '已发布' }).count())) {
    await autoRow.getByTestId('v-publish').click()
    const force = page.getByTestId('v-force-publish')
    if (await force.isVisible().catch(() => false)) await force.click()
    await expect(page.locator('tr', { hasText: '已发布' })).toBeVisible({ timeout: 20_000 })
  }
  await page.waitForTimeout(600)
  await page.screenshot({ path: `${SHOTS}/06-versions.png` })

  // ── 准备请假 + 代课(07/08 两张图的素材)──
  const leaveDay = await pickLeaveDay(page, sid)
  const teachers = await get(page, `/api/teachers?semester_id=${sid}`)
  const wang = teachers.find((t: { name: string }) => t.name === '王大明')
  const existing = await get(page, `/api/leaves?semester_id=${sid}`)
  if (!existing.length && wang) {
    const aps = (await post(page, `/api/leaves?semester_id=${sid}`, {
      teacher_id: wang.id, leave_type: 'sick', start_date: leaveDay, end_date: leaveDay,
    })).affected_periods
    expect(aps.length, '请假当天没有课——课表没发布成功?').toBeGreaterThan(0)
    for (const ap of aps.slice(0, 2)) {
      const rec = await get(page, `/api/affected-periods/${ap.id}/recommendations`)
      if (rec.candidates?.length) {
        await page.request.put(`/api/affected-periods/${ap.id}/substitution`,
          { data: { type: 'substitute', handler_teacher_id: rec.candidates[0].teacher_id } })
      }
    }
  }

  // ── 07 请假登记 ──
  await page.goto('/leaves')
  await selectSemester(page)
  await page.waitForTimeout(900)
  await page.screenshot({ path: `${SHOTS}/07-leaves.png` })

  // ── 08 今日调代课看板 ──
  await page.goto(`/daily-board?semester_id=${sid}&date=${leaveDay}`)
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(900)
  await page.screenshot({ path: `${SHOTS}/08-daily-board.png` })

  // ── 09 课表查询(含导出按钮)──
  await page.goto(`/timetable-query?semester_id=${sid}`)
  await expect(page.getByRole('heading', { name: '课表查询' })).toBeVisible({ timeout: 20_000 })
  await page.waitForTimeout(1200)
  await page.screenshot({ path: `${SHOTS}/09-timetable-query.png` })

  // ── 10 系统管理:备份与还原(先真的备一份,空清单的截图讲不清楚这一章)──
  await page.goto('/settings/system')
  await expect(page.getByTestId('backup-card')).toBeVisible({ timeout: 20_000 })
  const rows = page.getByTestId('backup-row')
  if (!(await rows.count())) {
    await page.getByTestId('backup-now').click()
    await expect(rows.first()).toBeVisible({ timeout: 60_000 })
  }
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${SHOTS}/10-backup.png` })

  // ── 11 调课:可对调节次清单(08.3)──
  // 07/08 的假单只代了前两节;若已没有待处理的节次,就再请一天假(下周三)当素材
  const leaves = await get(page, `/api/leaves?semester_id=${sid}`)
  const hasPending = leaves.some((l: { affected_periods: { status: string }[] }) =>
    l.affected_periods.some((p) => p.status === 'pending'))
  if (!hasPending && wang) {
    const [y, m, d] = leaveDay.split('-').map(Number)
    await post(page, `/api/leaves?semester_id=${sid}`, {
      teacher_id: wang.id, leave_type: 'official',
      start_date: iso(new Date(y, m - 1, d + 7)), end_date: iso(new Date(y, m - 1, d + 7)),
    })
  }
  await page.goto('/substitutions')
  await selectSemester(page)
  await page.getByTestId('sub-handle').first().click()
  await page.getByTestId('sub-swap').click()
  const swapPanel = page.getByTestId('sub-swap-panel')
  await expect(swapPanel.getByTestId('sub-swap-partner').first()).toBeVisible({ timeout: 20_000 })
  await swapPanel.scrollIntoViewIfNeeded()
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${SHOTS}/11-swap.png` })

  // ── 12 调课通知单(08.3 打印):点第一个可对调节次,再开打印页 ──
  await swapPanel.getByTestId('sub-swap-option').first().click()
  await expect(page.getByText(/已和 .+ 调课/)).toBeVisible({ timeout: 20_000 })
  const [slips] = await Promise.all([
    page.waitForEvent('popup'),
    page.getByTestId('sub-print-slip').first().click(),
  ])
  await slips.setViewportSize({ width: 1440, height: 900 })
  await expect(slips.getByTestId('slip-teacher').first()).toBeVisible({ timeout: 20_000 })
  await slips.waitForTimeout(700)
  await slips.screenshot({ path: `${SHOTS}/12-swap-slips.png` })
  await slips.close()

  // ── 13 代课通知单(08.2 打印):找一节已经代课的,开打印页 ──
  const subBtn = page.getByTestId('sub-print-slip-sub').first()
  await expect(subBtn).toBeVisible({ timeout: 20_000 })
  const [subSlips] = await Promise.all([
    page.waitForEvent('popup'),
    subBtn.click(),
  ])
  await subSlips.setViewportSize({ width: 1440, height: 900 })
  await expect(subSlips.getByTestId('slip-teacher').first()).toBeVisible({ timeout: 20_000 })
  await subSlips.waitForTimeout(700)
  await subSlips.screenshot({ path: `${SHOTS}/13-substitute-slips.png` })
  await subSlips.close()

  // ── 14 巡堂表(08.8 打印):王大明请假那天,代课老师与备注由系统带出 ──
  await page.goto(`/patrol-sheets/print?semester_id=${sid}&from=${leaveDay}&to=${leaveDay}`)
  await expect(page.getByTestId('patrol-page').first()).toBeVisible({ timeout: 20_000 })
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${SHOTS}/14-patrol-sheet.png` })
})
