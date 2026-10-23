import { defineConfig, devices } from '@playwright/test'

// E2E 验收:对「执行中的 Docker 全栈」(http://localhost)驱动真实浏览器。
// 一般执行(CI/无头):npm run e2e        → chromium(回归套件)
// 有头 + 放慢动作(给人观看):npm run e2e:headed
// 压测 / 手册截图(非回归,CI 不跑):npm run e2e:perf / npm run e2e:manual
const headed = process.env.HEADED === '1'
const ci = !!process.env.CI

const chrome = { ...devices['Desktop Chrome'] }

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  // CI 失败时留下可诊断产物(trace + HTML 报告);本机维持轻量 list
  retries: 0,
  reporter: ci ? [['list'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost',
    screenshot: 'only-on-failure',
    trace: ci ? 'retain-on-failure' : 'on-first-retry',
    launchOptions: { slowMo: headed ? 500 : 0 },
  },
  projects: [
    {
      // 回归验收套件(CI 跑这个)。排除两支「非验收」spec:
      //   manual-shots:操作手册截图产生器,需另一台已灌示范资料的 :8081 测试站
      //   perf-page-load:60 班压测,执行久且 p95 门槛受 runner 效能影响易 flaky
      name: 'chromium',
      use: chrome,
      testIgnore: ['**/manual-shots.spec.ts', '**/perf-page-load.spec.ts'],
    },
    { name: 'perf', use: chrome, testMatch: '**/perf-page-load.spec.ts' },
    { name: 'manual', use: chrome, testMatch: '**/manual-shots.spec.ts' },
  ],
})
