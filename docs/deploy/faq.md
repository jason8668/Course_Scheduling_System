# 常见问题 FAQ

## 安装与启动

**Q:`docker compose up -d` 后开网页看到「502」或「无法连线」。**
容器可能还在启动(尤其首次要跑资料库迁移)。等 20–30 秒再试,并看状态:

```bash
docker compose ps          # 看是否都 healthy
docker compose logs api    # 看 api 是否卡在迁移或报错
```

**Q:`docker compose ps` 有容器一直 restarting。**
看该容器 log 找原因:

```bash
docker compose logs --tail=50 <服务名>   # 例如 api / worker / postgres
```

常见:`.env` 的 `DATABASE_URL` 与 `POSTGRES_*` 帐密不一致;`SECRET_KEY` 未设。

**Q:80 埠被占用,启动失败(port is already allocated)。**
改 `.env` 的 `HTTP_PORT`(例如 `8080`)再 `docker compose up -d`,改用 `http://<主机IP>:8080`。

**Q:校内其他电脑连不到。**
确认用的是主机的**区网 IP**(非 `localhost`),且主机防火墙放行该埠。手机/平板需与主机同一网段(同一 Wi-Fi)。

---

## 帐号与登录

**Q:忘记管理员密码怎么办?**
若你还记得 `.env` 的初始 `ADMIN_PASSWORD`,那是**首次登录**用的;登录后改过的密码存在资料库。若连改过的都忘了,目前需由具资料库存取权者重设。最务实的做法是**还原一份记得密码的旧备份**(见[备份指南](backup.md)),或联系维护者。请妥善保管管理员密码。

**Q:还原备份后大家被登出了。**
这是预期行为。还原会替换整个资料库(含帐号),为安全起见系统会强制所有人以还原时点的帐密重新登录。

**Q:老师收不到调代课 Email。**
Email 为**选配**;未在「系统管理」设置 SMTP 时,只有站内通知(铃铛),系统一切正常。要寄 Email 需填学校的 SMTP 主机信息,并可按「寄测试信」当场验证。

---

## 资料与备份

**Q:我的资料存在哪?会不会不见?**
存在 Docker volume `pgdata`。只要不删这个 volume,`docker compose down` / 重启 / 升级都不会动到资料。**但主机硬碟坏掉 volume 会一起没**,所以务必做[异地备援](backup.md)。

**Q:`docker compose down` 会删资料吗?**
不会。`down` 只停止并移除容器,volume 保留。**只有 `docker compose down -v` 的 `-v` 会删 volume(含你的资料)**,请勿误用。

**Q:怎么把系统搬到新主机?**
新主机装好空系统 → 旧主机下载一份备份 `.dump` → 新主机「系统管理 → 上传还原」。详见[备份指南](backup.md)。

---

## 效能与规模

**Q:自动排课很慢或跑不出来。**
排课是计算密集工作,受班级数、约束复杂度影响。建议主机 ≥ 4 核 8GB。无解时系统会给「冲突定位」报告,依提示放宽条件或补资源。可设置求解逾时(默认 10 分钟),逾时取当前最佳解。

**Q:页面偶尔转圈久。**
自动排课/大量导出时 worker 较忙,但与 api 分离,一般操作不受影响。自 v1.1 起排课(`worker`)与导出/备份(`worker-ops`)分属两个容器,**排课进行中按导出仍是秒回**。若持续缓慢,查主机资源(`docker stats`)是否吃紧。

**Q:导出/备份时出现「维运背景服务(worker-ops)没有在执行」。**

你的 `docker-compose.yml` 少了 `worker-ops` 这个容器(多半是用了旧版的 compose 档)。它负责导出、备份、还原、寄信与每日自动备份——没有它,这些功能全都没人处理,而且**每日自动备份是无声停摆的**。

取得最新的 compose 档再重启即可,资料不受影响:

```bash
curl -fLO https://raw.githubusercontent.com/begin0808/Course_Scheduling_System/main/docker-compose.yml
docker compose up -d
docker compose ps          # 应看到六个容器,含 worker 与 worker-ops
```

**Q:导出课表 / 备份失败,说「背景忙碌或逾时」。**

`worker-ops` 有在跑但没做完。查它的 log:

```bash
docker compose ps worker-ops
docker compose logs --tail=50 worker-ops
```

PDF/PNG 导出在低阶机器上偶尔会超过 90 秒;主机吃紧(`docker stats`)时先让自动排课跑完再试。

---

## 升级与版本

**Q:怎么知道有没有新版、这版改了什么?**
v1.2.3 起,系统管理员登录后:有新版时右上角会出现「有新版本 vX.Y.Z」,「系统管理 → 系统版本」可看到目前版本、最新正式版,并连到更新内容与[升级指南](upgrade.md)。系统**只提醒、不会自动升级**。也可以直接看专案 [CHANGELOG.md](../../CHANGELOG.md) 与 GitHub Releases。

**Q:新版本提醒会把学校资料传出去吗?可以关掉吗?**
不会。系统每天最多一次向 GitHub 读取本专案**公开的**最新版本信息(一个 GET 请求),不送出任何学校资料。学校主机不能连外时,只会在系统版本卡片显示「无法连线」,不影响任何功能。若不希望主机连外,在 `.env` 加上 `UPDATE_CHECK_ENABLED=false` 后执行 `docker compose up -d` 即可关闭。

**Q:怎么看目前是哪一版?**
左侧选单最下方会显示版本号(v1.2.3 起)。回报问题时附上版本号,会比较容易查。

**Q:升级会不会弄坏资料?**
资料表结构变更由 `api` 启动时自动、向前相容地迁移,资料保留。仍建议升级前先「立即备份」。破坏性变更(若有)会在 CHANGELOG 该版本以 ⚠️ 标注。

---

## 其他

**Q:可以多所学校共用一套吗?**
本系统设计为**单校自架**,一所学校一套部署,资料彼此隔离、最单纯也最安全。多校请各自部署。

**Q:如何完全移除?**

```bash
docker compose down -v     # ⚠️ 连同资料 volume 一起删除,不可复原,请先备份!
```

**Q:找不到答案 / 想回报问题?**
到专案 GitHub 开 Issue(见 [CONTRIBUTING.md](../../CONTRIBUTING.md))。回报时附上 `docker compose logs` 相关片段会更快解决。
