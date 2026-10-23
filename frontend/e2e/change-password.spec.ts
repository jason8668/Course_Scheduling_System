import { expect, test } from '@playwright/test'

/**
 * 首次登录强制改密——**每一位新用户进入系统的第一个界面**。
 *
 * 为什么值得一支专属测试:这一页只有在「被强制改密」的状态下进得去(路由守卫会把
 * 非强制状态的人导回仪表板),先前所有测试都是走 API 改密码,从没有人点过这个界面。
 * 而 v1.1.1 修掉的那只虫(系统管理页整页渲染失败)正是这样溜过两个版本的——
 * 没有 e2e 覆盖的页面,坏掉时没有任何人会知道。这一页若坏了,新用户连门都进不来。
 *
 * 帐号 e2e_newuser 由 seed_e2e 每次重设回「首次登录」状态(本测试会把它用掉)。
 */

const USER = 'e2e_newuser'
const OLD_PW = 'e2enewuser1234'
const NEW_PW = 'e2echanged5678'

const SHOTS = 'e2e/screenshots'

test('首次登录:强制改密页挡住去路、验证输入,改完才能进入系统', async ({ page }) => {
  await page.goto('/login')
  await page.getByPlaceholder('请输入帐号').fill(USER)
  await page.getByPlaceholder('请输入密码').fill(OLD_PW)
  await page.getByRole('button', { name: '登录' }).click()

  // ① 登录后被导到改密页,而且**页面真的渲染出来**(这是本测试的核心:整页空白就必红)
  await page.waitForURL(/change-password/, { timeout: 15_000 })
  await expect(page.getByText('变更密码')).toBeVisible()
  await expect(page.getByTestId('cp-forced')).toContainText('首次登录')
  await expect(page.getByTestId('cp-submit')).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/cp-1-forced.png` })

  // ② 后端也挡(不是只有前端导向):未改密前功能性 API 一律 403
  const blocked = await page.request.get('/api/semesters')
  expect(blocked.status(), '强制改密期间后端就该挡住,不能只靠前端守卫').toBe(403)

  // ③ 想绕过去看别页?守卫会把人送回来
  await page.goto('/')
  await page.waitForURL(/change-password/, { timeout: 15_000 })

  const oldInput = page.getByTestId('cp-old').locator('input')
  const newInput = page.getByTestId('cp-new').locator('input')
  const confirmInput = page.getByTestId('cp-confirm').locator('input')

  // ④ 新密码太短 → 前端就挡下,不必等后端。
  //    顺带守住「一次送出只跑一次」:按钮先前同时挂了 submit 与 @click,每次送出跑两遍,
  //    在成功路径上等于送出两次改密请求,第二次必然回「原密码错误」。
  await oldInput.fill(OLD_PW)
  await newInput.fill('short')
  await confirmInput.fill('short')
  await page.getByTestId('cp-submit').click()
  const tooShort = page.getByText('新密码至少需 8 个字元')
  await expect(tooShort.first()).toBeVisible()
  expect(await tooShort.count(), '同一次送出不该出现两则讯息(重复触发)').toBe(1)

  // ⑤ 两次输入不一致(最常见的手误)。这里用 Enter 送出,顺便确认键盘操作也走得通
  await newInput.fill(NEW_PW)
  await confirmInput.fill(`${NEW_PW}x`)
  await confirmInput.press('Enter')
  const mismatch = page.getByText('两次输入的新密码不一致')
  await expect(mismatch.first()).toBeVisible()
  expect(await mismatch.count(), '同一次送出不该出现两则讯息(重复触发)').toBe(1)

  // ⑥ 原密码打错 → 后端的讯息要真的传到界面上(不是笼统的「变更密码失败」)
  await oldInput.fill('wrongpassword')
  await confirmInput.fill(NEW_PW)
  await page.getByTestId('cp-submit').click()
  await expect(page.getByText('原密码错误')).toBeVisible()

  // ⑦ 正确填写 → 改密成功并离开这一页
  await oldInput.fill(OLD_PW)
  await newInput.fill(NEW_PW)
  await confirmInput.fill(NEW_PW)
  await page.getByTestId('cp-submit').click()
  await expect(page.getByText('密码已更新')).toBeVisible()
  await expect(page).not.toHaveURL(/change-password/)

  // ⑧ 改完之后 API 就通了(强制状态确实解除,不是只有界面跳走)
  await expect.poll(async () => (await page.request.get('/api/semesters')).status())
    .toBe(200)

  // ⑨ 新密码真的能用,而且不会再被要求改密
  await page.request.post('/api/auth/logout')
  await page.goto('/login')
  await page.getByPlaceholder('请输入帐号').fill(USER)
  await page.getByPlaceholder('请输入密码').fill(NEW_PW)
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 15_000 })
  await expect(page).not.toHaveURL(/change-password/)
})

/**
 * #10:**纯教师角色**的首次登录。教师可进的页面比组长少,改密码页先前不在那份清单里,
 * 于是「导去改密码 → 教师不能进 → 导回课表查询 → 又要求改密码」互踢,界面卡在 /login
 * 完全不动(回报者必须强制关闭分页)。组长帐号走同一条路却正常,所以这一支要用教师帐号。
 *
 * 帐号 e2e_newteacher 由 seed_e2e 每次重设回「首次登录」状态。
 */
const T_USER = 'e2e_newteacher'
const T_OLD_PW = 'e2enewteacher1234'
const T_NEW_PW = 'e2eteacherchanged5678'

test('首次登录(纯教师角色):不会卡在登录页,改完密码进得了课表查询', async ({ page }) => {
  await page.goto('/login')
  await page.getByPlaceholder('请输入帐号').fill(T_USER)
  await page.getByPlaceholder('请输入密码').fill(T_OLD_PW)
  await page.getByRole('button', { name: '登录' }).click()

  // ① 真的离开 /login 并且界面有东西(卡死时网址会停在 /login)
  await page.waitForURL(/change-password/, { timeout: 15_000 })
  await expect(page.getByTestId('cp-forced')).toContainText('首次登录')
  await expect(page.getByTestId('cp-submit')).toBeVisible()

  // ② 改密成功 → 进到教师可用的页面(教师没有仪表板权限,应落在课表查询)
  await page.getByTestId('cp-old').locator('input').fill(T_OLD_PW)
  await page.getByTestId('cp-new').locator('input').fill(T_NEW_PW)
  await page.getByTestId('cp-confirm').locator('input').fill(T_NEW_PW)
  await page.getByTestId('cp-submit').click()
  await expect(page.getByText('密码已更新')).toBeVisible()
  await page.waitForURL(/timetable-query/, { timeout: 15_000 })
  await expect(page.getByTestId('header-change-password')).toBeVisible()
})

/** 用户自己要改密码时的入口:右上角「修改密码」(先前只有首次登录进得去这一页)。 */
test('一般用户可自行修改密码,也可以取消返回', async ({ page }) => {
  await page.goto('/login')
  await page.getByPlaceholder('请输入帐号').fill('e2e_teacher')
  await page.getByPlaceholder('请输入密码').fill('e2eteacher1234')
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL(/timetable-query/, { timeout: 15_000 })

  await page.getByTestId('header-change-password').click()
  await page.waitForURL(/change-password/, { timeout: 15_000 })
  await expect(page.getByTestId('cp-forced')).toHaveCount(0)  // 不是被强制的

  await page.getByTestId('cp-cancel').click()
  await page.waitForURL(/timetable-query/, { timeout: 15_000 })
})
