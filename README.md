# 排课与调代课系统 · Course Scheduling System

[![CI](https://github.com/begin0808/Course_Scheduling_System/actions/workflows/ci.yml/badge.svg)](https://github.com/begin0808/Course_Scheduling_System/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**开源免费、单校自架、纯 Web 的中小学排课与调代课系统。** 适用小学、初中、普通型高中、综合型高中、技术型高中,以**教学组长**的日常工作流程为中心设计。

从学期基础资料、手动与自动排课(OR-Tools CP-SAT 引擎),到学期中最繁琐的请假、代课、调课、通知与课时统计,一套涵盖。以 Docker Compose 一键部署在校内一台主机上,资料不出校。

> **English summary:** A free, open-source (MIT), self-hosted, web-based course-scheduling and teacher-substitution system for Taiwanese K–12 schools. It covers the school-timetabling office's full workflow: semester/period setup, manual drag-and-drop scheduling, automatic scheduling via an OR-Tools CP-SAT engine with human-readable conflict explanation, and the day-to-day of leave requests, substitute assignment, notifications, and substitution-hour reporting. One school, one self-hosted deployment (no multi-tenant SaaS). One-command Docker Compose install. UI is Traditional Chinese with Taiwan educational terminology.

---

## 功能总览

| 领域 | 内容 |
|---|---|
| **基础资料** | 学期/节次表(多学制范本)、教师/班级/科目/场地、Excel 导入、设置精灵、开新学期复制、混合学制(班级↔节次表指派) |
| **配课与手动排课** | 配课管理(跑班群组、协同教学、连堂)、课时即时统计、拖拉式周课表、单格冲突检查(<100ms)、多草稿版本管理与发布 |
| **自动排课** | OR-Tools CP-SAT 引擎,H1–H10 硬约束 + S1–S8 软约束加权;背景求解含即时进度;**无解时以教务语言定位冲突**并支援部分排课 |
| **调代课** | 请假登记与受影响节次展开、代课推荐引擎、调课验证、指派即生效、站内+Email 通知与确认、今日看板与 A4 公告打印、月结课时统计(Excel) |
| **报表/导出** | 班级/教师/场地课表导出 Excel / PDF(内嵌中文字型)/ PNG、全校总表、批次 zip |
| **维运** | 每日自动备份 + 手动备份 / 下载 / 上传还原(还原前自动保护、还原后强制重登)、稽核纪录、RBAC(管理员/主任/组长/教师) |

---

## 快速开始

需先安装 [Docker](https://docs.docker.com/get-docker/)。**完整步骤(含 Windows / Linux / NAS)见 [部署手册](docs/deploy/README.md)。**

### 一键安装脚本(最简单)

下载后执行,回答校名、管理员密码、埠号三个问题即可。金钥自动产生、埠号冲突自动闪开,不必手改 `.env`。

**Windows(PowerShell)**:

```powershell
Invoke-WebRequest https://raw.githubusercontent.com/begin0808/Course_Scheduling_System/main/install.ps1 -OutFile install.ps1
.\install.ps1
```

**Linux / macOS / NAS**:

```bash
curl -fLO https://raw.githubusercontent.com/begin0808/Course_Scheduling_System/main/install.sh
bash install.sh
```

> 刻意设计成「先下载、再执行」而非 `curl | sh`——这是要进学校主机的东西,请先打开看过内容。

### 拉取官方映像(推荐)

```bash
mkdir scheduling && cd scheduling
curl -fLO https://raw.githubusercontent.com/begin0808/Course_Scheduling_System/main/docker-compose.yml
curl -fL  https://raw.githubusercontent.com/begin0808/Course_Scheduling_System/main/.env.example -o .env
# 编辑 .env:改 ADMIN_PASSWORD、SCHOOL_NAME、SECRET_KEY
docker compose pull
docker compose up -d
```

> **Windows 用户**:上面是 bash 语法,PowerShell 的 `curl` 是 `Invoke-WebRequest` 的别名、
> 吃不懂 `-fLO`。请改用[安装指南](docs/deploy/install.md)里的 PowerShell 版本下载指令。

### 从原始码建置

```bash
git clone https://github.com/begin0808/Course_Scheduling_System.git
cd Course_Scheduling_System
cp .env.example .env      # 改 ADMIN_PASSWORD、SCHOOL_NAME、SECRET_KEY
docker compose up -d      # 首次会建置映像,需数分钟
```

启动后开浏览器连 `http://<主机IP>`(本机为 <http://localhost>),以 `.env` 的管理员帐密登录,依设置精灵完成建置。

**想先试看看?** 还没建学期时,到「系统管理 → 示范资料」按一下,会建出一所完整的虚构初中(18 班、48 位教师、384 笔配课),十几秒就能跑出全校课表——不必先手 key 资料就能把排课、调代课、导出、备份整套流程走过一遍。

- 健康检查:`http://localhost/api/health` → `{"status":"ok"}`
- 容器状态:`docker compose ps`(六个容器皆应 healthy)

### 硬体最低需求

2 核 / 4GB RAM / 10GB 磁碟(自动排课建议 4 核 8GB)。支援 x86-64 与 ARM64(NAS / 树莓派)。

---

## 界面

| 排课工作台(拖拉排课、三视角、即时冲突) | 自动排课(进度、软约束达成度) |
|---|---|
| ![排课工作台](docs/manual-img/04-workbench.png) | ![自动排课](docs/manual-img/05-auto-schedule.png) |

| 今日调代课看板(可打印 A4 通知单) | 课表查询与导出(Excel / PDF / PNG) |
|---|---|
| ![今日调代课](docs/manual-img/08-daily-board.png) | ![课表查询](docs/manual-img/09-timetable-query.png) |

完整逐章图解见[教学组长操作手册](https://begin0808.github.io/Course_Scheduling_System/)。

---

## 文件

| 文件 | 内容 |
|---|---|
| [**教学组长操作手册**](https://begin0808.github.io/Course_Scheduling_System/)（[原始档](docs/index.html)） | 给用户:设置精灵、配课、排课、调代课、导出、备份、FAQ(11 章图文网页) |
| [**功能总览**](https://begin0808.github.io/Course_Scheduling_System/features.html)（[原始档](docs/features.html)） | 目前版本的全部功能、已知限制与规划中项目(一页看完) |
| [部署手册](docs/deploy/README.md) | 给安装者:安装、升级、备份、网域 HTTPS、FAQ |
| [架构设计](docs/architecture.md) | 需求、资料模型、排课引擎、技术栈(规格权威来源) |
| [开发任务卡](docs/tasks.md) | Milestone 与逐卡实作纪录 |
| [变更纪录](CHANGELOG.md) | 各版本变更 |
| [贡献指南](CONTRIBUTING.md) | 开发环境、程序风格、测试、发布流程 |

> **离线阅读**:上表 `docs/` 下的每份 `.md` 都有一份对应的 `.html`(如 `docs/deploy/install.html`),
> 附侧边目录与深/浅色切换,双击即可用浏览器开,不必连网、不必装软件——机房里没网路时特别好用。
> 这些 HTML 由 `python scripts/build_docs.py` 从 Markdown 产生,**请勿直接编辑**;改完 `.md` 重跑一次即可。

---

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3 + TypeScript + Vite + Pinia + Naive UI |
| 后端 | Python 3.12 + FastAPI + SQLAlchemy 2 + Pydantic v2 |
| 排课引擎 | Google OR-Tools CP-SAT(RQ + Redis 背景执行) |
| 导出 | openpyxl(Excel)、WeasyPrint(PDF,内嵌 Noto CJK)、poppler(PNG) |
| 资料库 | PostgreSQL 16 |
| 反向代理 | Caddy(内网 HTTP;设网域即自动 HTTPS) |
| 部署 | Docker Compose(6 容器:web / api / worker(排课)/ worker-ops(导出·备份·定时)/ postgres / redis) |

---

## 专案状态

**v1.3.0 已发行(2026-10-18)。** 六大里程碑 M0–M5 全部完成,功能齐备并经完整验收(后端 654 项单元/整合测试、50 项 Playwright 端对端测试涵盖全部 20 个页面,每次提交皆对真实 Docker 全栈跑过)。官方映像(amd64 + arm64)已发布于 GHCR。

v1.3.0 支援**单双周课程**(同一节单周、双周轮流上不同的课,排课、请假代课、调课、巡堂表、课时都分单双周;⚠️ 首次改动资料表结构,升级前请先备份);v1.2.19 支援**日薪代课**(小学常见:月结统计把课时与日薪分开列)并可**整批指派代课**(整张假单或整天一次派给同一位老师);v1.2.18 可**检查课表**(发布前列出冲堂、教师不可排时段等冲突;事后修改不可排时段时当场提示已排的课);v1.2.17 修正登录按一次送出两笔请求(输错密码约第 3 次就被锁定);v1.2.15、v1.2.16 修正跑班群组的两个问题(同一位老师在群组里重复配课时自动排课会排出撞课的课表;同一格有多笔同科目配课时,手动排课把每日节数重复计算);v1.2.12~v1.2.14 可打印**巡堂表**并导出 Excel(依当天的调代课结果产生,社团另出分组巡堂单);v1.2.10、v1.2.11 让**初中小、完全中学**跨部上课的老师,课表与通知单都标出实际上课时间,两部节数不同(初中七节、高中八节)也不会漏课;v1.2.9 可一次导出**全校教师课表**(总表与批次打包);v1.2.8 可用 Excel **批次更新既有教师**(新学年职务异动),并能**停用/启用教师登录帐号**(离职教师保留历史纪录又进不来);v1.2.7 补上**学期起讫日期**的填写与修改(先前界面上无处可填,导致请假被挡);v1.2.6 修掉第一批外部用户回报的三个问题(教师帐号首次登录卡死、无法事后补开教师帐号、未排课务清单过长时拖不动),并可在界面上自行修改与重设密码;v1.2.5 可打印**教师代课通知单与班级代课通知单**(照学校纸本格式,代课时可选计费方式);v1.2.4 的调代课处理会写出处置方式(代课或调课、哪天补课);v1.2.3 起系统会显示目前版本,并在有新版时提醒系统管理员(只提醒、不自动升级);v1.2.2 可打印**教师调课通知单与班级调课通知单**(照学校纸本格式);v1.2.1 补上**调课**的操作界面——请假(含研习)的节次可直接列出双方都有空的对调节次,支援跨周(最多四周)与连堂,补课日也会出现在今日看板。v1.2.0 起另有**一键示范资料**,装好后两分钟内就能看到一张排好的全校课表。

**请直接从最新版开始安装**(见上方快速开始);`v1.3.0` 是目前建议使用的版本。各版变更见 [CHANGELOG](CHANGELOG.md),开发历程见 [docs/tasks.md](docs/tasks.md)。

系统仍在实际校园环境试用中,若你是第一批用户,欢迎通过 [Issues](https://github.com/begin0808/Course_Scheduling_System/issues) 回报任何问题。

---

## 回报问题与意见回馈

发现错误、有功能建议,或想分享贵校的使用经验,都非常欢迎:

- **回报问题 / 提出建议**:于本专案开 [GitHub Issue](https://github.com/begin0808/Course_Scheduling_System/issues)(附上操作步骤与 `docker compose logs` 片段会更快解决)
- **来信联络**:专案开发者 **国立南大附中 李佳恩老师** — [begin0808@gmail.com](mailto:begin0808@gmail.com)

这套系统是为第一线教学组长而写的,你的实际使用回馈对它的改进最有帮助。

## 授权

[MIT](LICENSE) — 可自由使用、修改、散布。欢迎各校自架与二次开发。

执行时使用的第三方元件与其授权见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)(皆与 MIT 相容)。
