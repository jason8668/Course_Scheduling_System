import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { SEM_END, SEM_START, THU, WED, WED2 } from './dates'
import { deleteSemesterByYearTerm, login } from './helpers'

const SHOTS = 'e2e/screenshots'

const post = async (page: Page, url: string, data: object) =>
  (await page.request.post(url, { data })).json()

async function selectSemester(page: Page, year: number) {
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${year} 学年度第 1 学期` }).click()
}

/**
 * 王师周三第一节国文请假。陈师同科空堂、周师非本科当天在校、吴师该节有课(被过滤)。
 * 回传 { sid, affectedId }。
 */
async function seed(page: Page, year: number) {
  const sem = await post(page, '/api/semesters', {
    academic_year: year, term: 1, template_key: 'junior_high',
    start_date: SEM_START, end_date: SEM_END,
  })
  const sid = sem.id
  const subjects: Record<string, number> = {}
  for (const s of await (await page.request.get(`/api/subjects?semester_id=${sid}`)).json()) {
    subjects[s.name] = s.id
  }
  const subject = async (name: string) => {
    if (!subjects[name]) {
      subjects[name] = (await post(page, `/api/subjects?semester_id=${sid}`, { name })).id
    }
    return subjects[name]
  }
  const teacher = async (name: string, subs: string[]) => (await post(
    page, `/api/teachers?semester_id=${sid}`,
    { name, base_periods: 20, subject_ids: await Promise.all(subs.map(subject)) })).id
  // get-or-create:同学期班名唯一(M6-5),同一个班不能建第二次
  const classes: Record<string, number> = {}
  const klass = async (name: string) => {
    if (!classes[name]) {
      classes[name] = (await post(page, `/api/class-units?semester_id=${sid}`,
        { grade: 7, name, track: 'junior_high' })).id
    }
    return classes[name]
  }

  const T: Record<string, number> = {
    王师: await teacher('王师', ['国文']),
    陈师: await teacher('陈师', ['国文']),
    周师: await teacher('周师', ['数学']),
    吴师: await teacher('吴师', ['数学']),
  }
  const tt = (await post(page, `/api/timetables?semester_id=${sid}`, { name: '草稿A' })).id
  const c0 = await klass('701')
  const wed = (await (await page.request.get(
    `/api/class-units/${c0}/period-table`)).json()).periods
    .filter((p: { weekday: number; type: string }) => p.weekday === 3 && p.type === 'regular')

  const place = async (t: string, subj: string, kls: string, pidx: number) => {
    const a = await post(page, `/api/assignments?semester_id=${sid}`, {
      class_id: await klass(kls), subject_id: await subject(subj), periods_per_week: 1,
      teachers: [{ teacher_id: T[t] }], block_rules: [],
    })
    await page.request.post(`/api/timetables/${tt}/entries`, {
      data: { course_assignment_id: a.id, weekday: 3, period_no: wed[pidx].period_no, span: 1 },
    })
  }
  await place('王师', '国文', '701', 0) // 被请假
  await place('周师', '数学', '703', 2) // 当天在校,第一节空
  await place('吴师', '数学', '704', 0) // 该节有课 → 过滤
  await page.request.post(`/api/timetables/${tt}/publish?force=true`)

  const leave = await post(page, `/api/leaves?semester_id=${sid}`, {
    teacher_id: T['王师'], leave_type: 'sick',
    start_date: WED, end_date: WED,
  })
  return { sid, affectedId: leave.affected_periods[0].id as number }
}

// ── 验收①:推荐排序(同科第一)+ 硬性过滤 + 指派 ──
test('调代课处理:推荐同科优先、过滤有课者,指派后标记已确认', async ({ page }) => {
  test.setTimeout(120_000)
  const YEAR = 140
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)
  await seed(page, YEAR)

  await page.goto('/substitutions')
  await selectSemester(page, YEAR)

  // 展开待处理节次 → 看推荐
  await page.getByTestId('sub-handle').first().click()
  const panel = page.getByTestId('sub-panel')
  await expect(panel).toBeVisible()

  const candidates = panel.getByTestId('sub-candidate')
  await expect(candidates).toHaveCount(2) // 陈师(同科)、周师(当天在校);吴师有课被过滤
  await expect(candidates.first()).toContainText('陈师')
  await expect(candidates.first()).toContainText('同科目教师')
  await expect(panel).not.toContainText('吴师')
  await page.screenshot({ path: `${SHOTS}/sub-1-recommend.png` })

  // 计费方式:病假默认公费代课(印在代课通知单上)
  await expect(panel.getByTestId('sub-funding')).toContainText('公费代课')

  // 指派第一名(陈师)
  await candidates.first().getByTestId('sub-pick').click()
  await expect(page.getByText('已指派 陈师 代课')).toBeVisible()
  const period = page.getByTestId('sub-period').first()
  await expect(period).toContainText('已确认')
  await expect(period.getByTestId('sub-handler')).toContainText('代课 → 陈师')
  await page.screenshot({ path: `${SHOTS}/sub-2-assigned.png` })

  // 代课通知单:陈师教师单 + 701 班级单;格子写「日期/科目/班级[代]」与「日期/科目/老师[代]」
  const [slips] = await Promise.all([
    page.waitForEvent('popup'),
    period.getByTestId('sub-print-slip-sub').click(),
  ])
  await expect(slips.getByTestId('slip-teacher')).toHaveCount(1)
  await expect(slips.getByTestId('slip-class')).toHaveCount(1)
  const teacherSlip = slips.getByTestId('slip-teacher')
  await expect(teacherSlip).toContainText('代课　通知单')
  await expect(teacherSlip).toContainText('代课教师：陈师')
  await expect(teacherSlip).toContainText('请假教师：王师')
  await expect(teacherSlip.getByTestId('slip-leave-meta')).toContainText(`日期：${WED} ~ ${WED}`)
  await expect(teacherSlip.getByTestId('slip-leave-meta')).toContainText('假别：病假')
  await expect(teacherSlip.getByTestId('slip-leave-meta')).toContainText('计费方式：公费代课')
  await expect(teacherSlip.getByTestId('slip-cell')).toHaveText(
    new RegExp(String.raw`${WED}\s*国文\s*701\[代\]`))
  await expect(slips.getByTestId('slip-class')).toContainText('班级代课　通知单')
  await expect(slips.getByTestId('slip-class').getByTestId('slip-cell')).toHaveText(
    new RegExp(String.raw`${WED}\s*国文\s*陈师\[代\]`))
  await expect(slips.locator('th.corner svg line')).toHaveCount(2)  // 每张一条斜线
  await slips.screenshot({ path: `${SHOTS}/sub-9-substitute-slips.png`, fullPage: true })
  await slips.close()

  // 假单标题列也能一次印齐
  await expect(page.getByTestId('sub-print-leave-sub')).toContainText('1 节')

  // 调代课纪录页:代课单批次打印
  await page.goto('/substitution-log')
  await selectSemester(page, YEAR)
  await expect(page.getByTestId('log-print-sub-slips')).toContainText('1 节')
  await page.goto('/substitutions')
  await selectSemester(page, YEAR)

  // 撤回 → 退回待处理
  await page.getByTestId('sub-period').first().getByTestId('sub-undo').click()
  await expect(page.getByText('已撤回处置')).toBeVisible()
  await expect(page.getByTestId('sub-period').first()).toContainText('待处理')

  await deleteSemesterByYearTerm(page, YEAR, 1)
})

// ── 验收③:全校无人可代 → 提示并班/自习,可直接改采 ──
test('调代课处理:无人可代时提示并班/自习并可直接设置', async ({ page }) => {
  test.setTimeout(120_000)
  const YEAR = 141
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)

  // 只有王师与陈师,且陈师该节也有课 → 无人可代
  const sem = await post(page, '/api/semesters', {
    academic_year: YEAR, term: 1, template_key: 'junior_high',
    start_date: SEM_START, end_date: SEM_END,
  })
  const sid = sem.id
  const guo = (await (await page.request.get(
    `/api/subjects?semester_id=${sid}`)).json()).find(
    (s: { name: string }) => s.name === '国文').id
  const wang = (await post(page, `/api/teachers?semester_id=${sid}`,
    { name: '王师', base_periods: 20, subject_ids: [guo] })).id
  const chen = (await post(page, `/api/teachers?semester_id=${sid}`,
    { name: '陈师', base_periods: 20, subject_ids: [guo] })).id
  const c1 = (await post(page, `/api/class-units?semester_id=${sid}`,
    { grade: 7, name: '701', track: 'junior_high' })).id
  const c2 = (await post(page, `/api/class-units?semester_id=${sid}`,
    { grade: 7, name: '702', track: 'junior_high' })).id
  const tt = (await post(page, `/api/timetables?semester_id=${sid}`, { name: '草稿A' })).id
  const wed = (await (await page.request.get(
    `/api/class-units/${c1}/period-table`)).json()).periods
    .filter((p: { weekday: number; type: string }) => p.weekday === 3 && p.type === 'regular')
  for (const [tid, cid] of [[wang, c1], [chen, c2]] as const) {
    const a = await post(page, `/api/assignments?semester_id=${sid}`, {
      class_id: cid, subject_id: guo, periods_per_week: 1,
      teachers: [{ teacher_id: tid }], block_rules: [],
    })
    await page.request.post(`/api/timetables/${tt}/entries`, {
      data: { course_assignment_id: a.id, weekday: 3, period_no: wed[0].period_no, span: 1 },
    })
  }
  await page.request.post(`/api/timetables/${tt}/publish?force=true`)
  await post(page, `/api/leaves?semester_id=${sid}`, {
    teacher_id: wang, leave_type: 'sick', start_date: WED, end_date: WED,
  })

  await page.goto('/substitutions')
  await selectSemester(page, YEAR)
  await page.getByTestId('sub-handle').first().click()

  await expect(page.getByTestId('sub-nocandidate')).toContainText('并班')
  await expect(page.getByTestId('sub-nocandidate')).toContainText('自习')
  await page.screenshot({ path: `${SHOTS}/sub-3-nocandidate.png` })

  // 直接改采自习
  await page.getByTestId('sub-selfstudy').click()
  await expect(page.getByText('已设为自习')).toBeVisible()
  await expect(page.getByTestId('sub-period').first()).toContainText('已确认')

  await deleteSemesterByYearTerm(page, YEAR, 1)
})

// ── v1.2.1:调课(使用学校回馈:只有代课、找不到调课)──
// 王师周三第一节 701 国文请假;陈师也教 701(周四第二节数学)、另有 702 周三第二节。
test('调代课处理:调课列出可对调节次,点击后成立并上看板', async ({ page }) => {
  test.setTimeout(120_000)
  const YEAR = 142
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)

  const sid = (await post(page, '/api/semesters', {
    academic_year: YEAR, term: 1, template_key: 'junior_high',
    start_date: SEM_START, end_date: SEM_END,
  })).id
  const subjects: Record<string, number> = {}
  for (const s of await (await page.request.get(`/api/subjects?semester_id=${sid}`)).json()) {
    subjects[s.name] = s.id
  }
  const subject = async (name: string) => {
    if (!subjects[name]) {
      subjects[name] = (await post(page, `/api/subjects?semester_id=${sid}`, { name })).id
    }
    return subjects[name]
  }
  const T: Record<string, number> = {}
  for (const [name, subs] of [['王师', ['国文']], ['陈师', ['数学', '自然']]] as const) {
    T[name] = (await post(page, `/api/teachers?semester_id=${sid}`, {
      name, base_periods: 20, subject_ids: await Promise.all(subs.map(subject)),
    })).id
  }
  const classes: Record<string, number> = {}
  for (const name of ['701', '702']) {
    classes[name] = (await post(page, `/api/class-units?semester_id=${sid}`,
      { grade: 7, name, track: 'junior_high' })).id
  }
  const periods = (await (await page.request.get(
    `/api/class-units/${classes['701']}/period-table`)).json()).periods
    .filter((p: { type: string }) => p.type === 'regular')
  const slot = (weekday: number, idx: number) =>
    periods.filter((p: { weekday: number }) => p.weekday === weekday)[idx].period_no
  const tt = (await post(page, `/api/timetables?semester_id=${sid}`, { name: '草稿A' })).id
  const place = async (t: string, subj: string, kls: string, weekday: number, idx: number) => {
    const a = await post(page, `/api/assignments?semester_id=${sid}`, {
      class_id: classes[kls], subject_id: await subject(subj), periods_per_week: 1,
      teachers: [{ teacher_id: T[t] }], block_rules: [],
    })
    await page.request.post(`/api/timetables/${tt}/entries`, {
      data: { course_assignment_id: a.id, weekday, period_no: slot(weekday, idx), span: 1 },
    })
  }
  await place('王师', '国文', '701', 3, 0) // 被请假
  await place('陈师', '数学', '701', 4, 1) // 同班 → 可互调
  await place('陈师', '自然', '702', 3, 1) // 别班 → 只有下周三换得成(本周三王师请假)
  await page.request.post(`/api/timetables/${tt}/publish?force=true`)
  await post(page, `/api/leaves?semester_id=${sid}`, {
    teacher_id: T['王师'], leave_type: 'personal', start_date: WED, end_date: WED,
  })

  const short = (iso: string) => {
    const [y, m, d] = iso.split('-').map(Number)
    const wd = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][new Date(y, m - 1, d).getDay()]
    return `${m}/${d}(${wd})`
  }

  await page.goto('/substitutions')
  await selectSemester(page, YEAR)
  await page.getByTestId('sub-handle').first().click()
  await page.getByTestId('sub-swap').click()

  const swapPanel = page.getByTestId('sub-swap-panel')
  const partner = swapPanel.getByTestId('sub-swap-partner')
  await expect(partner).toHaveCount(1)
  await expect(partner).toContainText('陈师')
  await expect(partner).toContainText('也教这班')
  const options = partner.getByTestId('sub-swap-option')
  await expect(options).toHaveCount(2) // 先只列同班:本周四、下周四
  await expect(options.first()).toContainText(`${short(THU)}`)
  await expect(options.first()).toContainText('701 数学')
  await partner.getByTestId('sub-swap-more').click() // 展开其他班:下周三 702
  await expect(options).toHaveCount(3)
  await expect(options.nth(2)).toContainText(`${short(WED2)}`)
  await expect(swapPanel).not.toContainText(short(WED)) // 请假当天不能补
  await page.screenshot({ path: `${SHOTS}/sub-4-swap-options.png` })

  // 放宽到 4 周:「本周与隔三周」的周四出现
  const [ty, tm, td] = THU.split('-').map(Number)
  const thu3 = new Date(ty, tm - 1, td + 21)
  const thu3Label = `${thu3.getMonth() + 1}/${thu3.getDate()}(周四)`
  await expect(swapPanel).not.toContainText(thu3Label)
  await swapPanel.getByTestId('sub-swap-weeks').click()
  await page.locator('.n-base-select-option', { hasText: '往后共 4 周' }).click()
  await expect(swapPanel).toContainText(thu3Label)

  await options.first().click()
  await expect(page.getByText('已和 陈师 调课')).toBeVisible()
  const period = page.getByTestId('sub-period').first()
  await expect(period).toContainText('已确认')
  // 清单写出处置方式与补课时间,分得出是调课不是代课
  await expect(period.getByTestId('sub-handler')).toContainText(`调课 → 陈师(王师 ${short(THU)} 第二节补课)`)

  // 调课通知单:陈师、王师各一张教师单 + 701 班级单;格子写「日期/科目/老师/[调MM-DD_星期节次]」
  const [slips] = await Promise.all([
    page.waitForEvent('popup'),
    period.getByTestId('sub-print-slip').click(),
  ])
  await expect(slips.getByTestId('slip-teacher')).toHaveCount(2)
  await expect(slips.getByTestId('slip-class')).toHaveCount(1)
  const mmdd = (iso: string) => iso.slice(5)
  const chenSlip = slips.getByTestId('slip-teacher').first()
  await expect(chenSlip).toContainText('教师调课通知单')
  await expect(chenSlip).toContainText('调课教师：陈师')
  await expect(chenSlip.getByTestId('slip-cell')).toHaveText(
    new RegExp(`${WED}\\s*数学\\s*陈师\\s*\\[调${mmdd(THU)}_42\\]`))
  await expect(slips.getByTestId('slip-teacher').nth(1).getByTestId('slip-cell')).toHaveText(
    new RegExp(`${THU}\\s*国文\\s*王师\\s*\\[调${mmdd(WED)}_31\\]`))
  await expect(slips.getByTestId('slip-class').getByTestId('slip-cell')).toHaveCount(2)
  // 表头斜线画在内容里(SVG),打印不会像背景一样被浏览器略过
  await expect(slips.locator('th.corner svg line')).toHaveCount(3)
  await slips.screenshot({ path: `${SHOTS}/sub-8-swap-slips.png`, fullPage: true })
  await slips.close()

  // 调代课纪录:筛选结果中的调课可一次打印
  await page.goto('/substitution-log')
  await selectSemester(page, YEAR)
  await expect(page.getByTestId('log-print-slips')).toContainText('1 节')

  // 今日看板(请假那天)标示调课与补课时间
  await page.goto(`/daily-board?semester_id=${sid}&date=${WED}`)
  await expect(page.getByTestId('board-row').first()).toContainText(`调课 · 陈师(补 ${THU}`)
  await page.screenshot({ path: `${SHOTS}/sub-5-swap-board.png` })

  // 补课那天(周四)的看板与 A4 公告单也列出换来的那一节:原任陈师、改由王师上
  await page.goto(`/daily-board?semester_id=${sid}&date=${THU}`)
  const makeup = page.getByTestId('board-row')
  await expect(makeup).toHaveCount(1)
  await expect(makeup).toContainText('701')
  await expect(makeup).toContainText('数学')
  await expect(makeup).toContainText('陈师')
  await expect(makeup).toContainText('调课补课')
  await expect(makeup).toContainText(`调课补课 · 王师(与 ${WED} `)
  await page.screenshot({ path: `${SHOTS}/sub-6-swap-makeup-board.png` })

  await page.goto(`/daily-board/print?semester_id=${sid}&date=${THU}`)
  const printRow = page.getByTestId('print-row')
  await expect(printRow).toHaveCount(1)
  await expect(printRow).toContainText('王师')
  await expect(printRow).toContainText(`与 ${WED}`)
  await page.screenshot({ path: `${SHOTS}/sub-7-swap-makeup-print.png` })

  // 请假的王师也收到补课通知
  const notes = await (await page.request.get(
    `/api/notifications?semester_id=${sid}&teacher_id=${T['王师']}`)).json()
  expect(notes.map((n: { title: string }) => n.title).join()).toContain('调课补课通知')

  await deleteSemesterByYearTerm(page, YEAR, 1)
})
