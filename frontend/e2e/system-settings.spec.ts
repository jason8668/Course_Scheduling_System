import { expect, test } from '@playwright/test'
import { login } from './helpers'

const SHOTS = 'e2e/screenshots'

/**
 * 系统管理页的回归测试。
 *
 * 这一页先前**完全没有 e2e 覆盖**,于是一个致命 bug 一路上了 v1.0.0 与 v1.1.0:
 * `System.vue` 呼叫 `useDialog()`,但 `App.vue` 没有挂 `<n-dialog-provider>`——
 * Naive 会在 setup 直接掷错,整页渲染不出来(侧边选单还在,内容区一片空白)。
 * 也就是说备份、还原、SMTP、重设精灵这四件事,用户根本点不进去。
 *
 * 因此本测试的第一个断言(卡片看得到)就是核心:页面只要 setup 掷错就是全白,必红。
 */
test('系统管理:三张卡片渲染、可立即备份并删除备份', async ({ page }) => {
  test.setTimeout(120_000)
  await login(page, 'e2e_admin', 'e2eadmin1234')

  await page.goto('/settings/system')
  await expect(page.getByRole('heading', { name: '系统管理' })).toBeVisible()

  // setup 若掷错(缺 dialog provider),以下三张卡片一张都不会出现
  await expect(page.getByTestId('smtp-status')).toBeVisible()
  await expect(page.getByTestId('backup-card')).toBeVisible()
  await expect(page.getByText('重新启动设置精灵')).toBeVisible()

  // 系统版本(v1.2.3):目前版本一定要有;是否有新版取决于 GitHub 与建置版号,这里不假设结果,
  // 只要求「查到了」或「明讲查不到」其中之一——绝不能卡在读取中或整张卡片坏掉
  const versionCard = page.getByTestId('version-card')
  await expect(versionCard.getByTestId('version-current')).not.toHaveText('读取中…', { timeout: 20_000 })
  await expect(page.getByTestId('app-version')).toContainText('版本')
  await expect(versionCard.getByTestId('version-check')).toBeVisible()
  await expect(versionCard.getByText(/上次检查/)).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/system-1-page.png` })

  // 立即备份 → 清单多一列(这条路径会打到 worker-ops 的 pg_dump)
  const rows = page.getByTestId('backup-row')
  const before = await rows.count()
  await page.getByTestId('backup-now').click()
  await expect(page.getByText('已建立备份')).toBeVisible({ timeout: 60_000 })
  await expect(rows).toHaveCount(before + 1)
  await page.screenshot({ path: `${SHOTS}/system-2-backup.png` })

  // 删除刚才那份,不留垃圾(最新的在最上面)
  await rows.first().getByRole('button', { name: '删除' }).click()
  await page.getByRole('button', { name: '确定' }).click()
  await expect(page.getByText('已删除备份')).toBeVisible()
  await expect(rows).toHaveCount(before)
})
