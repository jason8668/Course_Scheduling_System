# 贡献指南

欢迎回报问题与贡献程序。本专案为 MIT 授权、单校自架的排课与调代课系统,面向台湾中小学教学组长。

## 回报问题

到 GitHub 开 Issue,请尽量附上:

- 复现步骤、预期行为与实际行为。
- 环境:部署方式(拉映像 / 原始码)、`IMAGE_TAG` 或 commit、作业系统。
- 相关 log:`docker compose logs --tail=100 api`(或 worker/web)。**请先移除机密**(密码、`SECRET_KEY`)。

## 开发环境

### 热重载全栈

```bash
cp .env.example .env
docker compose -f docker-compose.dev.yml up
```

- 前端(热重载):<http://localhost:5173>
- API 互动文件:<http://localhost:8000/api/docs>

前后端原始码挂载进容器,存档即时生效。含 `mailhog`(拦截外送信,Web UI <http://localhost:8025>)须以 `--profile dev` 启动。

### 各自本机测试

```bash
# 后端
cd backend && pip install -e ".[dev]" && pytest
# 前端
cd frontend && npm install && npm run test
```

## 程序风格与质量门槛

送 PR 前请确保各项通过(CI 也会挡):

| 范围 | 指令 | 要求 |
|---|---|---|
| 后端 lint/格式 | `ruff check .` | 零错误 |
| 后端型别 | `mypy app` | 零错误 |
| 后端测试 | `pytest` | 全绿,且不使既有测试退步 |
| 前端 lint | `npm run lint` | 零错误 |
| 前端建置+型别 | `npm run build`(含 vue-tsc) | 通过 |
| 前端单元测试 | `npm run test` | 全绿 |

其他约定:

- **UI 文案一律简体中文、大陆教务用语**(节次、科任、配课、课时、跑班)。冲突/提示讯息用节次表中储存的名称(早自修/午休/第一节),不用内部 `period_no`。
- **资料库 schema 变更必附 Alembic 迁移**,且能从前一版顺向升级。
- solver 模组(`app/solver/`)不得 import `app.api` / `app.models`(以测试保证纯度)。
- **背景任务分两条伫列**:`default` 只跑自动排课(可占住 worker 数分钟),`ops` 跑导出/备份/还原/寄信与定时任务。新增背景任务时先问「这会不会跑很久」——会的话走 `default`,否则一律 `ops`,别让秒级任务排在排课后面。正式环境由 `worker` 与 `worker-ops` 两个容器分别守著(同一映像,见 `app/workers/worker.py`);开发用 compose 是单一行程同时守两条(dev 不在乎排课堵住导出)。
- **新增后端相依请一并给主版号上限**(`fastapi>=0.115,<1` 这种写法)。踩过:`redis` 只写下限,某次重建映像装到 redis-py 8,阻塞式取结果的行为变了,导出与备份在新环境全数逾时失败——而本机因为 pip 快取还是旧版,测不出来。映像每次发行都重新建置,不钉上限等于把用户的部署交给上游的发版节奏。
- 架构规格以 [docs/architecture.md](docs/architecture.md) 为准;与任务卡冲突时以架构文件为准并回报矛盾。

### E2E(Playwright)

对「执行中的 Docker 全栈」驱动真实浏览器。需先 `docker compose up -d`,再建立测试帐号(`e2e_scheduler` / `e2e_teacher` / `e2e_admin` / `e2e_newuser`,并将设置精灵标记完成):

```bash
docker compose exec -T api python -m app.scripts.seed_e2e

cd frontend
npx playwright install chromium   # 首次
npm run e2e            # 回归套件(无头;CI 跑的就是这个)
npm run e2e:headed     # 有头 + 放慢,可在萤幕上观看
npm run e2e:perf       # 60 班压测(执行久,非回归,CI 不跑)
npm run e2e:manual     # 操作手册截图产生器(需一套空资料库的站台,CI 不跑)
```

`seed_e2e` 是幂等的,**唯一例外是 `e2e_newuser`**:它每次都被重设回「首次登录待改密」状态,因为 `change-password.spec.ts` 必然会把这个状态用掉(那支测试就是去改密码的)。本机连续重跑 e2e 前记得重新 seed。

CI 的 `e2e` job 会在 runner 上建置三个映像、起全栈、seed 帐号后跑回归套件;E2E 未过不会发布映像。

**新增页面时请一并加 e2e。** 这条不是形式要求:v1.0.0 曾有一整页(系统管理)因为 setup 掷错而完全渲染不出来,备份/还原/SMTP 全都点不进去,却因为没有任何测试覆盖而溜过两个版本。目前 20 个路由全数有 e2e 造访,请维持这个状态。

### 操作手册截图

`npm run e2e:manual` 会产生 `docs/manual-img/` 的 14 张截图。它**自备示范资料**(115 学年度、8 位教师、3 班、24 笔配课),所以只要给它一套空的站台即可:

```bash
# 另起一套独立的栈(空资料库),.env 设 ADMIN_PASSWORD=DemoSetup2026!
docker compose -p manual --env-file <你的.env> up -d
E2E_BASE_URL=http://localhost:<port> npm run e2e:manual
```

介面改版(尤其是主题色、版面)后请重跑,别让手册停留在旧界面。

## 提交与 PR

- 从 `main` 开分支开发;PR 对回 `main`。
- Commit 讯息用祈使句、精简描述「做了什么、为什么」。
- PR 描述请逐条对照相关任务卡的验收标准,说明验证方式与结果。
- 不 force-push 共用分支;不绕过 hook 或签章(除非明确需要)。

## 开发流程(任务卡制)

本专案以 [docs/tasks.md](docs/tasks.md) 的 Milestone 任务卡推进:一次一张卡,实作 → 依卡上「验收标准」自我验证 → 回报 → 验收后才进下一张。完成后更新该卡核取方块为 `[x]` 并补「实作后」纪录。临时冒出的点子记入 tasks.md 末尾的 Backlog,不顺手实作。

## 发布新版本(维护者)

映像建置与发布已由 CI 自动化(见 [.github/workflows/ci.yml](.github/workflows/ci.yml)):

1. 确认 `main` 绿灯——**五个 job 全过**:backend / frontend / migrations / e2e / images。
2. 更新 `CHANGELOG.md`:把 `[Unreleased]` 内容整理到新版本标题下并注明日期,标注破坏性变更(⚠️)。同步更新 `README.md` 的专案状态、`docs/deploy/upgrade.md` 的钉选版本范例。
3. 打标签并推送:

   ```bash
   git tag -a v1.2.0 -m "v1.2.0(日期):一句话说明"
   git push origin v1.2.0
   ```

4. `v*` 标签触发 CI 的 `images` job,建置并推送**双架构(amd64 + arm64)**映像到 GHCR:
   - `ghcr.io/begin0808/course_scheduling_system-api`
   - `ghcr.io/begin0808/course_scheduling_system-worker`
   - `ghcr.io/begin0808/course_scheduling_system-web`

   每个映像会推 `:latest`、`:<版本标签>`(即 `github.ref_name`)与 `:<commit sha>` 三个 tag。`main` push 仅建 amd64;**版本标签才建双架构**(arm64 走模拟,约需 20 分钟)。
5. **等映像真的上架再建 Release**——标签推上去的当下映像还在建,太早公开连结会让人 `docker compose pull` 扑空。确认方式:

   ```bash
   docker buildx imagetools inspect ghcr.io/begin0808/course_scheduling_system-api:<版本> | grep Platform
   ```

6. 在 GitHub 建立 Release,关联该标签,贴上该版 CHANGELOG 内容,勾选 **Set as the latest release**。
7. **发布前最后一道**:在干净环境拉**正式映像**跑一次(不是本机建的那份)——CI 验的是从原始码建的映像,用户拉到的是 `images` job 产出的那份,两者从未同时被验证过。至少走到:六容器 healthy → 首次登录改密 → 设置精灵 → 系统管理页(**「系统版本」显示的目前版本须等于本次标签**,确认 `APP_VERSION` 有注入)→ 立即备份。
8. 用户升级:`.env` 设 `IMAGE_TAG=<版本>` → `docker compose pull && docker compose up -d`(见 [docs/deploy/upgrade.md](docs/deploy/upgrade.md))。`IMAGE_TAG` 即对应此处推送的版本标签。

## 授权

贡献即表示你同意以 [MIT](LICENSE) 授权释出你的贡献。
