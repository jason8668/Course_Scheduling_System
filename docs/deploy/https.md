# 网域与 HTTPS(选配)

**校内网路使用不需要这篇** —— 用 `http://<主机IP>` 即可,免设置。

本篇适用于:要让**校外**(在家、手机行动网路)也能连,并使用网域 + HTTPS 加密。系统的 web 容器用 Caddy,设置网域后会**自动申请并续期 Let's Encrypt 凭证**,你不必手动处理凭证。

---

## 你需要先具备

1. **一个网域名**(例如 `school.example.edu.tw`,或自备的网域)。
2. 一台**具公开 IP 的主机**(校内对外服务器,或云端 VPS)。
3. 能编辑该网域的 **DNS**,把网域指向主机 IP。
4. 主机的 **80 与 443 埠可从外网连入**(防火墙/资安设备放行;Let's Encrypt 签发需要 80 埠)。

---

## 设置步骤

### 1. DNS 指向主机

在网域管理处新增一笔 **A 记录**:

```
school.example.edu.tw   →   你的主机公开 IP
```

等 DNS 生效(数分钟到数十分钟)。可用 `nslookup school.example.edu.tw` 确认解析到正确 IP。

### 2. 在 `.env` 设置网域

```ini
SITE_ADDRESS=school.example.edu.tw
HTTPS_PORT=443
```

- `SITE_ADDRESS` 一填成网域,Caddy 就会自动走 HTTPS 并把 HTTP 转址到 HTTPS。
- 不填(或留 `:80`)则维持内网 HTTP 模式。

### 3. 重启

```bash
docker compose up -d
docker compose logs -f web     # 观察凭证申请过程
```

第一次启动时 Caddy 会向 Let's Encrypt 申请凭证,log 出现 `certificate obtained successfully` 即成功。之后用 `https://school.example.edu.tw` 连线,浏览器显示锁头。

凭证存放于 `caddydata` volume,重启不会重新申请;续期由 Caddy 自动处理。

---

## 在云端 VPS 上部署(校内无法对外时)

若学校网路无法对外开埠,可租一台小型 VPS(1–2 vCPU / 2–4GB RAM 即可跑基本功能,自动排课建议 4 核 8GB):

1. 依[安装指南](install.md)在 VPS 上装好 Docker 并起好系统。
2. 依本篇设置网域与 `SITE_ADDRESS`。
3. VPS 防火墙/安全群组放行 **80、443**;**不要**对外开放 5432(PostgreSQL)、6379(Redis)、8000(api)——这些只在容器内部网路互通,compose 默认也不对外映射它们。

> **资料落在 VPS 上**,务必依[备份指南](backup.md)设好异地备援(定期下载 `.dump` 到校内或云端硬碟)。VPS 若停租或损毁,只有异地备份能救回资料。

---

## 常见状况

**凭证申请失败(log 出现 challenge failed / timeout)**
- 多半是 80/443 没对外通,或 DNS 还没指到这台主机。先确认外网能连到主机的 80 埠。
- 网域必须是**真实可解析**的公开网域;`localhost` 或纯 IP 无法申请公开凭证。

**只想要 HTTPS 但用自签/内部凭证(纯内网)**
- Caddy 对非公开网域可用其内部 CA。进阶需求请参考 [Caddy 官方文件](https://caddyserver.com/docs/),或改用纯 HTTP 内网部署。

**改了网域要换成另一个**
- 改 `.env` 的 `SITE_ADDRESS` 后 `docker compose up -d`。旧凭证留在 `caddydata` 不影响。

**80 埠被学校既有网站占用**
- HTTPS 自动签发需要 80 埠做验证,较难共用。建议此情境改用独立 VPS,或与网管协调子网域与埠。
