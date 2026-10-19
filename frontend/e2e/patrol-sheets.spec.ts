import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { SEM_END, SEM_START, WED } from './dates'
import { deleteSemesterByYearTerm, login } from './helpers'

/**
 * 巡堂表(v1.2.12):调代课之后,原本的巡堂表会指向错的老师。
 * 从「今日调代课看板」印出当天真正的样子——代课老师与备注由系统带出;
 * 社团这种大型跑班群组另出分组巡堂单。
 */
const YEAR = 156

const post = async (p: Page, url: string, data: object) => {
  const r = await p.request.post(url, { data })
  expect(r.ok(), `${url} → ${r.status()} ${await r.text()}`).toBeTruthy()
  return r.json()
}

test('巡堂表:看板开启打印页,代课与社团分组单都正确带出', async ({ page }) => {
  test.setTimeout(120_000)
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)

  // 失败时也要清掉测试学期:残留的学期会让后面的设置精灵、教师端测试看到非预期的界面
  try {
  const sem = await post(page, '/api/semesters', {
    academic_year: YEAR, term: 1, template_key: 'junior_high', start_date: SEM_START, end_date: SEM_END,
  })
  const q = `?semester_id=${sem.id}`
  const subjects: { id: number; name: string }[] = await (await page.request.get(`/api/subjects${q}`)).json()
  const chinese = subjects.find((s) => s.name === '国文')!.id
  const teacher = async (name: string, subject: number) =>
    (await post(page, `/api/teachers${q}`, { name, subject_ids: [subject] })).id as number
  const wang = await teacher('王老师', chinese)
  const chen = await teacher('陈老师', chinese)
  const c701 = (await post(page, `/api/class-units${q}`, { grade: 7, name: '701', track: 'junior_high' })).id
  const c702 = (await post(page, `/api/class-units${q}`, { grade: 7, name: '702', track: 'junior_high' })).id
  const periods: { weekday: number; name: string; period_no: number }[] =
    (await (await page.request.get(`/api/class-units/${c701}/period-table`)).json()).periods
  const pno = (name: string) => periods.find((p) => p.weekday === 3 && p.name === name)!.period_no

  const tt = (await post(page, `/api/timetables${q}`, { name: '草稿A' })).id
  const place = (assignment: number, name: string) => post(page, `/api/timetables/${tt}/entries`,
    { course_assignment_id: assignment, weekday: 3, period_no: pno(name), span: 1 })

  // 王老师周三第一节 701 国文
  const a = await post(page, `/api/assignments${q}`, {
    class_id: c701, subject_id: chinese, periods_per_week: 1, teachers: [{ teacher_id: wang }], block_rules: [],
  })
  await place(a.id, '第一节')

  // 社团:两班一个跑班群组、四个社团,周三第六节
  const room = (await post(page, `/api/rooms${q}`, { name: '体育馆' })).id
  const unit = (await post(page, `/api/scheduling-units${q}`, { name: '社团', class_ids: [c701, c702] })).id
  const clubs = ['羽球社', '桌球社', '棒球社', '漫画社']
  let first = 0
  for (const [i, name] of clubs.entries()) {
    const subject = (await post(page, `/api/subjects${q}`, { name })).id
    const club = await post(page, `/api/assignments${q}`, {
      scheduling_unit_id: unit, subject_id: subject, periods_per_week: 1,
      teachers: [{ teacher_id: await teacher(`社团师${i + 1}`, subject) }], block_rules: [],
      room_id: i === 0 ? room : null,
    })
    if (i === 0) first = club.id
  }
  await place(first, '第六节')     // 群组内的课会一起排进同一时段
  expect((await page.request.post(`/api/timetables/${tt}/publish?force=true`)).ok()).toBeTruthy()

  // 王老师周三请假,陈老师代课
  const leave = await post(page, `/api/leaves${q}`,
    { teacher_id: wang, leave_type: 'sick', start_date: WED, end_date: WED })
  const sub = await page.request.put(`/api/affected-periods/${leave.affected_periods[0].id}/substitution`,
    { data: { type: 'substitute', handler_teacher_id: chen } })
  expect(sub.ok()).toBeTruthy()

  // 从看板开启(新分页)
  await page.goto(`/daily-board?semester_id=${sem.id}&date=${WED}`)
  const [sheet] = await Promise.all([
    page.waitForEvent('popup'),
    page.getByTestId('board-patrol').click(),
  ])
  await expect(sheet.getByTestId('patrol-page')).toHaveCount(2, { timeout: 20_000 })   // 上午、下午

  const morning = sheet.getByTestId('patrol-page').first()
  await expect(morning).toContainText('巡堂纪录')
  await expect(morning).toContainText('第 1~4 节')
  await expect(morning.getByTestId('patrol-class')).toHaveText(['701', '702'])
  // 701 第一节:代课的陈老师,备注「代课」;请假的王老师不在表上
  const cell = morning.getByTestId('patrol-cell').first()
  await expect(cell).toContainText('国文')
  await expect(cell).toContainText('陈老师')
  await expect(morning).not.toContainText('王老师')
  await expect(morning.getByTestId('patrol-note').first()).toHaveText('代课')
  await expect(morning.getByTestId('patrol-legend')).toContainText('授课情形')

  // 下午第六节:社团塞不进格子,主表只写群组与组数,另出分组巡堂单
  const afternoon = sheet.getByTestId('patrol-page').nth(1)
  await expect(afternoon).toContainText('共 4 组')
  const list = sheet.getByTestId('patrol-group-list')
  await expect(list).toHaveCount(1)
  await expect(list).toContainText('社团巡堂单')
  await expect(list).toContainText('第六节')
  await expect(list.getByTestId('patrol-group-item')).toHaveCount(4)
  await expect(list.getByTestId('patrol-group-item').first()).toContainText('羽球社')
  await expect(list.getByTestId('patrol-group-item').first()).toContainText('体育馆')
  await sheet.screenshot({ path: 'e2e/screenshots/patrol-1-sheet.png', fullPage: true })
  await sheet.close()

  // v1.2.14:同一份内容可导出 Excel(当天、整周),下载后自行增减栏位
  for (const [testid, name] of [
    ['board-patrol-xlsx', `巡堂表_${WED}.xlsx`],
    ['board-patrol-week-xlsx', /^巡堂表_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}\.xlsx$/],
  ] as [string, string | RegExp][]) {
    const [file] = await Promise.all([
      page.waitForEvent('download'),
      page.getByTestId(testid).click(),
    ])
    if (typeof name === 'string') expect(file.suggestedFilename()).toBe(name)
    else expect(file.suggestedFilename()).toMatch(name)
  }
  } finally {
    await deleteSemesterByYearTerm(page, YEAR, 1)
  }
})
