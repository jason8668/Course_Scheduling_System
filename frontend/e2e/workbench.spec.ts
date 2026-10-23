import { expect, test } from '@playwright/test'
import type { Locator, Page } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

const YEAR = 126
const SHOTS = 'e2e/screenshots'

// 初中范本可排课节次(period_no):1=早自习、6=午休,其余为一般课
const SLOTS = [2, 3, 4, 5, 7, 8, 9]
const SUBJECTS = ['国文', '数学', '英文', '自然', '社会', '艺文', '健体']

/** 以 dispatchEvent + 真实 DataTransfer 驱动 HTML5 拖放,才能在「放下前」断言冲突红框。 */
async function newDataTransfer(page: Page) {
  return page.evaluateHandle(() => new DataTransfer())
}
async function dragOver(page: Page, source: Locator, target: Locator) {
  const dt = await newDataTransfer(page)
  await source.dispatchEvent('dragstart', { dataTransfer: dt })
  await target.dispatchEvent('dragenter', { dataTransfer: dt })
  return { dt, end: () => source.dispatchEvent('dragend', { dataTransfer: dt }) }
}
async function dragDrop(page: Page, source: Locator, target: Locator) {
  const dt = await newDataTransfer(page)
  await source.dispatchEvent('dragstart', { dataTransfer: dt })
  await target.dispatchEvent('dragenter', { dataTransfer: dt })
  await target.dispatchEvent('drop', { dataTransfer: dt })
}
const cell = (page: Page, weekday: number, period: number) =>
  page.locator(`[data-weekday="${weekday}"][data-period="${period}"]`)

test('排课工作台:冲突红框、拖放排课、锁定、拖回移除、Ctrl+Z、三视角一致、排满归零', async ({ page }) => {
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })

  // ── 前置(API):学期 + 2 班 + 8 位教师 + 8 科 + 配课 ──
  await deleteSemesterByYearTerm(page, YEAR, 1)
  const sem = await (await page.request.post('/api/semesters', {
    data: { academic_year: YEAR, term: 1, template_key: 'junior_high' },
  })).json()
  const sid = sem.id
  const post = async (url: string, data: object) =>
    (await page.request.post(url, { data })).json()

  const c301 = await post(`/api/class-units?semester_id=${sid}`, { grade: 3, name: '301', track: 'junior_high' })
  const c302 = await post(`/api/class-units?semester_id=${sid}`, { grade: 3, name: '302', track: 'junior_high' })

  // 王师教 301 国文,同时教 302 数学二(用来制造教师冲突)
  const wang = await post(`/api/teachers?semester_id=${sid}`, { name: '王师' })
  const others = []
  for (let i = 1; i < SUBJECTS.length; i++) {
    others.push(await post(`/api/teachers?semester_id=${sid}`, { name: `师${i}` }))
  }
  const teacherOf = (i: number) => (i === 0 ? wang : others[i - 1])

  const aIds: number[] = []
  for (let i = 0; i < SUBJECTS.length; i++) {
    const s = await post(`/api/subjects?semester_id=${sid}`, { name: SUBJECTS[i] })
    const a = await post(`/api/assignments?semester_id=${sid}`, {
      class_id: c301.id, subject_id: s.id, periods_per_week: 5,
      teachers: [{ teacher_id: teacherOf(i).id, is_lead: true }], block_rules: [],
    })
    aIds.push(a.id)
  }
  const s302 = await post(`/api/subjects?semester_id=${sid}`, { name: '数学二' })
  const a302 = await post(`/api/assignments?semester_id=${sid}`, {
    class_id: c302.id, subject_id: s302.id, periods_per_week: 5,
    teachers: [{ teacher_id: wang.id, is_lead: true }], block_rules: [],
  })

  // ── 进入工作台(首次载入自动建立草稿)──
  await page.goto('/scheduling/workbench')
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${YEAR} 学年度第 1 学期` }).click()
  await expect(page.getByTestId('wb-remaining')).toHaveText('剩 35 节')

  // 取得草稿 id,并让王师在 302 班的周五第七节(period_no 9)先有课
  const tts = await (await page.request.get(`/api/timetables?semester_id=${sid}`)).json()
  const ttId = tts[0].id
  await page.request.post(`/api/timetables/${ttId}/entries`, {
    data: { course_assignment_id: a302.id, weekday: 5, period_no: 9, span: 1 },
  })
  await page.reload()
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${YEAR} 学年度第 1 学期` }).click()

  // ── ① 冲突红框:拖 301 国文(王师)到周五第七节 ──
  const tray国文 = page.getByTestId('wb-tray-国文')
  const conflictCell = cell(page, 5, 9)
  const drag = await dragOver(page, tray国文, conflictCell)
  await expect(conflictCell).toHaveClass(/is-conflict/)
  await expect(conflictCell).toContainText('教师王师')
  // 该格在宽表右侧,整页截图看不到 → 直接截该格元素以便人工查看红框与原因
  await conflictCell.screenshot({ path: `${SHOTS}/wb-1-conflict-cell.png` })
  await page.screenshot({ path: `${SHOTS}/wb-1-conflict.png` })
  await drag.end()

  // ── ② 可放绿框 + 放入:周一第一节(period_no 2)──
  const okCell = cell(page, 1, 2)
  const d2 = await dragOver(page, tray国文, okCell)
  await expect(okCell).toHaveClass(/is-droppable/)
  await okCell.dispatchEvent('drop', { dataTransfer: d2.dt })
  await expect(okCell).toContainText('国文')
  await expect(page.getByTestId('wb-remaining')).toHaveText('剩 34 节')
  await page.screenshot({ path: `${SHOTS}/wb-2-placed.png` })

  // ── ③ Ctrl+Z 复原 ──
  await page.keyboard.press('Control+z')
  await expect(okCell).not.toContainText('国文')
  await expect(page.getByTestId('wb-remaining')).toHaveText('剩 35 节')

  // 重新放入供后续步骤使用
  await dragDrop(page, page.getByTestId('wb-tray-国文'), okCell)
  await expect(okCell).toContainText('国文')

  // ── ④ 点卡片锁定 → 不可拖曳;再点解锁 ──
  const card = okCell.locator('.tg-card')
  await card.click()
  await expect(okCell.locator('.tg-lock')).toBeVisible()
  await expect(card).toHaveAttribute('draggable', 'false')
  await card.click()
  await expect(okCell.locator('.tg-lock')).toHaveCount(0)
  await expect(card).toHaveAttribute('draggable', 'true')

  // ── ⑤ 拖回未排清单 → 移除 ──
  await dragDrop(page, card, page.getByTestId('wb-tray'))
  await expect(okCell).not.toContainText('国文')
  await expect(page.getByTestId('wb-remaining')).toHaveText('剩 35 节')

  // ── ⑥ 排完整班:其余经 API 依计划排入(每科一天一节,不触发 H2/H10)──
  for (let i = 0; i < SUBJECTS.length; i++) {
    for (let d = 1; d <= 5; d++) {
      const r = await page.request.post(`/api/timetables/${ttId}/entries`, {
        data: { course_assignment_id: aIds[i], weekday: d, period_no: SLOTS[i], span: 1 },
      })
      expect(r.status(), `${SUBJECTS[i]} 周${d} 节次${SLOTS[i]}`).toBe(201)
    }
  }
  await page.reload()
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${YEAR} 学年度第 1 学期` }).click()

  // 未排清单归零(验收①)
  await expect(page.getByTestId('wb-remaining')).toHaveText('剩 0 节')
  await expect(page.getByTestId('wb-tray-empty')).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/wb-3-full.png` })

  // ── ⑦ 三视角一致(验收②):班级视角排的课,教师视角立即可见 ──
  await page.getByTestId('wb-view-teacher').click()
  await page.getByTestId('wb-teacher').click()
  await page.locator('.n-base-select-option', { hasText: '王师' }).first().click()
  // 王师:301 国文(周一~周五第一节)+ 302 数学二(周五第七节)
  await expect(cell(page, 1, 2)).toContainText('国文')
  await expect(cell(page, 5, 9)).toContainText('数学二')
  await page.screenshot({ path: `${SHOTS}/wb-4-teacher-view.png` })

  await deleteSemesterByYearTerm(page, YEAR, 1)
})

/**
 * #8:未排课务清单超过一个界面高度时,卷到底部的卡片拖不进课表格。
 * 原因是清单跟著整页变长,卷到底部时左侧课表格已经被卷出界面,没有可以放开的目标。
 * 修法是清单限高自己卷动 + 卡片 sticky,课表格永远留在界面上。
 */
const YEAR_TRAY = 152

test('排课工作台:未排课务很多时,清单自己卷动,最底下的卡片仍拖得进课表', async ({ page }) => {
  test.setTimeout(120_000)
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await page.setViewportSize({ width: 1280, height: 720 })

  await deleteSemesterByYearTerm(page, YEAR_TRAY, 1)
  const sem = await (await page.request.post('/api/semesters', {
    data: { academic_year: YEAR_TRAY, term: 1, template_key: 'junior_high' },
  })).json()
  const sid = sem.id
  const post = async (url: string, data: object) =>
    (await page.request.post(url, { data })).json()

  // 一个班、12 笔各 1 节的课务:卡片数量稳定超过一个界面高度
  const klass = await post(`/api/class-units?semester_id=${sid}`,
    { grade: 3, name: '301', track: 'junior_high' })
  const names = ['甲科', '乙科', '丙科', '丁科', '戊科', '己科',
    '庚科', '辛科', '壬科', '癸科', '子科', '丑科']
  for (const name of names) {
    const subject = await post(`/api/subjects?semester_id=${sid}`, { name })
    const teacher = await post(`/api/teachers?semester_id=${sid}`, { name: `${name}师` })
    await post(`/api/assignments?semester_id=${sid}`, {
      class_id: klass.id, subject_id: subject.id, periods_per_week: 1,
      teachers: [{ teacher_id: teacher.id, is_lead: true }], block_rules: [],
    })
  }
  await post(`/api/timetables?semester_id=${sid}`, { name: '草稿A' })

  await page.goto('/scheduling/workbench')
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${YEAR_TRAY} 学年度第 1 学期` }).click()
  const trayList = page.getByTestId('wb-tray-list')
  await expect(trayList).toBeVisible()
  await expect(page.getByTestId(`wb-tray-${names[0]}`)).toBeVisible()

  // ① 清单自己有卷轴(不是把整页撑长)
  const scrollable = await trayList.evaluate((el) => el.scrollHeight > el.clientHeight + 1)
  expect(scrollable, '课务多时清单应该自己卷动').toBeTruthy()

  // ② 卷到清单底部之后,左侧课表格仍在界面内
  await trayList.evaluate((el) => { el.scrollTop = el.scrollHeight })
  const last = page.getByTestId(`wb-tray-${names[names.length - 1]}`)
  await expect(last).toBeInViewport()
  const target = cell(page, 3, SLOTS[0])
  await expect(target).toBeInViewport()

  // ③ 最底下那张卡片拖得进课表格
  await dragDrop(page, last, target)
  await expect(target).toContainText(names[names.length - 1])

  await deleteSemesterByYearTerm(page, YEAR_TRAY, 1)
})
