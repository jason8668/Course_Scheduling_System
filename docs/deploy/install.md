# 安装指南

从零把系统架起来。整个过程约 15 分钟(含下载映像)。

**有两条路,选一条就好:**

| | 适合谁 | 你要做的事 |
|---|---|---|
| **[一键安装脚本](#一键安装推荐)** | 绝大多数人 | 装 Docker → 执行脚本 → 回答三个问题 |
| [手动安装](#手动安装) | 想完全掌握每一步、或环境特殊 | 下面的步骤 0～3 |

两者做的事完全一样,脚本只是把手动的步骤 1～3 自动化(含产生金钥、闪开被占用的埠号)。

---

## 一键安装(推荐)

### 步骤 A:先装好 Docker

同下方[步骤 0](#步骤-0先装好-docker),装完请确认 Docker 已启动。

### 步骤 B:下载脚本,看过再执行

脚本刻意设计成「先下载、再执行」而不是一行指令直接跑——**这是要进学校主机的东西,你应该能先打开看过内容**。

**Windows(PowerShell)**:

```powershell
cd $HOME\Downloads
Invoke-WebRequest https://raw.githubusercontent.com/begin0808/Course_Scheduling_System/main/install.ps1 -OutFile install.ps1
notepad install.ps1        # 先看过(可略)
.\install.ps1
```

> 若出现「因为这个系统上停用指令码执行」的讯息,先执行一次:
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`
> (只对这个视窗有效,关掉就恢复原设置。)

**Linux / macOS / NAS**:

```bash
curl -fLO https://raw.githubusercontent.com/begin0808/Course_Scheduling_System/main/install.sh
less install.sh            # 先看过(可略)
bash install.sh
```

### 脚本会做什么

1. 检查 Docker 装好没、引擎有没有在跑(没有的话直接告诉你该怎么办)
2. 建立安装资料夹,下载 `docker-compose.yml`
3. **问你三件事**:校名、管理员密码(输入时不显示)、对外埠号
4. 自动产生 `SECRET_KEY`(不需要 openssl)
5. 写出 `.env`——你不必开文字编辑器
6. 下载映像、启动六个容器、确认系统回应
7. 印出**校内其他电脑要连的网址**,并开启浏览器

埠号 80 或 443 被其他服务占用时,脚本会自动改用可用的埠并告诉你。

### 常用选项

```bash
bash install.sh --path /opt/scheduling    # 指定安装位置(Windows 用 -InstallPath)
bash install.sh --port 8080               # 指定埠号
bash install.sh --skip-start              # 只产生设置档,先不启动(想自己看过 .env)
bash install.sh --reconfigure             # 已装过,要重新设置校名/密码
```

装好之后直接跳到[验证安装成功](#验证安装成功)。

### 想在同一台主机再装一套(测试环境)

**这件事有陷阱,务必看一下。** Docker 用「专案名称」决定哪些容器与资料属于同一套,本系统固定叫 `scheduling`。所以在同一台主机的另一个资料夹重跑安装,**不会产生第二套,而是会接管既有那一套**——连资料库也是同一份。

脚本会侦测到这个情况并挡下来,提示你改用不同的专案名称:

```bash
# Linux / macOS / NAS
bash install.sh --project-name scheduling-test --path ~/scheduling-test --port 8090

# Windows PowerShell
.\install.ps1 -ProjectName scheduling-test -InstallPath D:\scheduling-test -Port 8090
```

这样两套会完全独立:容器、资料库、备份各走各的,可以同时执行(埠号要不同)。专案名称会记在该资料夹的 `.env` 里,之后在该目录下 `docker compose` 各项指令都会自动沿用,不必每次加参数。

> 要移除测试环境:`cd` 到它的资料夹执行 `docker compose down -v`(`-v` 会一并删掉资料)。
> **执行前务必确认自己在测试环境的资料夹**,在正式环境的资料夹下这条指令会删光你的排课资料。

---

## 手动安装

以下是脚本背后实际做的事。想自己一步步来、或环境特殊(例如需要走 Proxy)时看这段。

---

## 步骤 0:先装好 Docker

系统以 Docker Compose 运行,主机只需要装 **Docker**(含 Docker Compose,现代版本已内建)。

### Windows

最快的方式是用 Windows 内建的套件管理员,在 PowerShell 执行一行:

```powershell
winget install Docker.DockerDesktop
```

或到 [Docker Desktop for Windows](https://docs.docker.com/desktop/install/windows-install/) 下载安装档。

接著:

1. 安装时若提示启用 WSL 2,照著开启即可。
2. **装完请重新开机**(WSL 2 需要)。
3. 开启 Docker Desktop,等左下角变绿灯(Engine running)。
4. 开「终端机 / PowerShell」,执行 `docker --version` 有版本号即成功。

### Linux(Ubuntu / Debian,校内服务器常见)

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # 让目前用户免 sudo 用 docker(需重新登录生效)
```

重新登录后 `docker compose version` 有版本号即成功。

### NAS(Synology / QNAP)

- **Synology**:「套件中心」安装 **Container Manager**(旧机型为 Docker)。DSM 7.2+ 的 Container Manager 内建 Compose,可直接在「专案」页贴上 `docker-compose.yml`。
- **QNAP**:「App Center」安装 **Container Station**,其中的「应用程序(Applications)」支援 docker-compose.yml。
- NAS 记忆体建议 ≥ 4GB;自动排课较吃资源,尖峰时建议 8GB。

> NAS 图形介面的操作细节各机型略有差异,但核心都是「贴上 compose 设置 → 提供 .env 环境变数 → 建立专案」。以下命令列步骤同样适用于在 NAS 上开 SSH 操作。

---

## 步骤 1:取得设置档

### 方式 A:拉取官方预建映像(推荐)

只需要两个档案:`docker-compose.yml` 与 `.env`。建立一个空资料夹(例如 `scheduling`),放入本专案的 `docker-compose.yml`,并在同层建立 `.env`(见步骤 2)。

**Linux / macOS / Git Bash**:

```bash
mkdir scheduling && cd scheduling
# 下载 docker-compose.yml 与 .env.example(从专案 Releases 页或原始码取得)
curl -fLO https://raw.githubusercontent.com/begin0808/Course_Scheduling_System/main/docker-compose.yml
curl -fL  https://raw.githubusercontent.com/begin0808/Course_Scheduling_System/main/.env.example -o .env
```

**Windows PowerShell**:

```powershell
mkdir scheduling; cd scheduling
$base = "https://raw.githubusercontent.com/begin0808/Course_Scheduling_System/main"
Invoke-WebRequest "$base/docker-compose.yml" -OutFile docker-compose.yml
Invoke-WebRequest "$base/.env.example"       -OutFile .env
```

> Windows 请照上面这段,**不要照抄 bash 那段的 `curl`**。PowerShell 的 `curl` 是
> `Invoke-WebRequest` 的别名,吃不懂 `-fLO` 这种参数,会直接报错。真要用内建的
> curl 程序必须写全名 `curl.exe`。

### 方式 B:从原始码建置

```bash
git clone https://github.com/begin0808/Course_Scheduling_System.git
cd Course_Scheduling_System
cp .env.example .env
```

---

## 步骤 2:修改 `.env`(至少改两项)

用文字编辑器打开 `.env`,**最少**改这几项:

```ini
ADMIN_PASSWORD=改成你的管理员密码      # 首次登录后系统会再要求你改一次
SCHOOL_NAME=○○国民中学                # 显示在介面与导出的课表上
SECRET_KEY=改成一长串随机字元          # 见下方产生方式,务必更换
```

**产生随机 `SECRET_KEY`**(session 签章金钥,关系到登录安全,一定要换掉默认值):

```bash
openssl rand -hex 32        # Linux / macOS / Git Bash
```

Windows 没有内建 `openssl`(它是随 Git for Windows 一起装的),在 PowerShell 改用:

```powershell
$b = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
($b | ForEach-Object { $_.ToString('x2') }) -join ''
```

把印出来的那 64 个字元贴到 `SECRET_KEY=` 后面即可。

> 没改 `SECRET_KEY` 不会让系统起不来——程序侦测到仍是范例值时会自动换一把随机金钥。
> 但那把金钥只存在记忆体里,**容器一重启所有人就被登出**,所以还是设一个固定值为宜。

其余设置(资料库帐密、Redis、时区)维持默认即可。详细每一项说明见 `.env.example` 内的注解。

> **`.env` 含机密,切勿上传到 GitHub、云端硬碟或任何公开处。** 本专案的 `.gitignore` 已排除它。

---

## 步骤 3:启动

### 方式 A(拉取映像)

```bash
docker compose pull      # 下载官方映像(首次较久)
docker compose up -d     # 背景启动六个容器
```

### 方式 B(从原始码建置)

```bash
docker compose up -d     # 首次会自动建置映像,需数分钟
```

启动后首次会**自动执行资料库迁移**(建立所有资料表),你不需要手动做任何 SQL。

---

## 验证安装成功

```bash
docker compose ps        # 六个容器应皆为 running / healthy
curl http://localhost/api/health
# 预期回应:{"status":"ok"}
```

用浏览器开:

- 本机:<http://localhost>
- 校内其他电脑:`http://<主机的区网IP>`(例如 `http://192.168.1.50`,IP 用 `ipconfig` / `ip a` 查)

以 `.env` 设置的 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 登录,系统会要求你**首次改密码**,接著进入**设置精灵**,依界面五步骤建立学期、教师、班级、科目即可开始使用。

### 想先试看看再决定?载入示范资料

还没建任何学期时,到「系统管理 → 示范资料」按一下,系统会建出一所完整的虚构初中(台南市市立敦品初中:18 班、48 位教师、384 笔配课),十几秒就能跑出一张全校课表。适合评估阶段先把整套流程走过一遍,不必先手 key 几百笔资料。

**只有在系统完全没有学期时才能载入**,以免盖掉正式资料。试用完要正式启用时,建议重新安装一套干净的系统,不要把示范资料与真实资料混在一起。

---

## 硬体最低需求

| 项目 | 最低 | 建议(含自动排课) |
|---|---|---|
| CPU | 2 核 | 4 核 |
| 记忆体 | 4 GB | 8 GB |
| 磁碟 | 10 GB | 20 GB(含备份保留 30 份) |
| 架构 | x86-64 或 ARM64(NAS/树莓派可) | — |

官方映像同时提供 `linux/amd64` 与 `linux/arm64`,Docker 会自动挑选符合你主机的版本。

---

## 埠号被占用怎么办?

默认对外走 80 埠。若该埠已被其他服务使用,改 `.env`:

```ini
HTTP_PORT=8080
```

重新 `docker compose up -d`,改用 `http://<主机IP>:8080` 连线。

**另外要注意 443 埠**:系统会**无条件占用 443**,即使你没有启用 HTTPS。若主机上已有其他服务(例如另一套网站系统)占著 443,启动时会出现:

```
Bind for 0.0.0.0:443 failed: port is already allocated
```

这个讯息只提 443,很容易误以为跟自己设的 80 埠有关。解法是在 `.env` 加一行改掉它:

```ini
HTTPS_PORT=8443
```

不影响内网以 HTTP 使用;日后真要启用网域 HTTPS 时再调整即可。(一键安装脚本会自动侦测并闪开。)

---

下一步:设置[每日自动备份与异地备援](backup.md);若要让校外也能连,见[网域与 HTTPS](https.md)。遇到问题见 [FAQ](faq.md)。
