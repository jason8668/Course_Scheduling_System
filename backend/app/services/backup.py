"""资料库备份与还原(M5-2)。

以 PostgreSQL 原生工具 pg_dump / pg_restore(custom 格式,可 --clean 还原)。这些工具
只装在 worker 映像,故实际 dump/restore 在 worker 执行;api 端负责清单、下载、上传与派工。

- 档名:`backup_YYYYMMDD_HHMMSS_<reason>.dump`,存放于共挂的 volume(config.backup_dir)。
- 保留 config.backup_keep 份,超出者由旧而新轮替删除。
  「升级前自动备份」(reason=preupgrade,v1.3.0)不参与轮替,由组长自己决定何时删除。
- 还原前先验证档头(custom 格式以 `PGDMP` 开头),非法档案直接拒绝、不动资料库(验收②)。
- 附件(#83):每份备份另带一个同名附件包 `backup_YYYYMMDD_HHMMSS_<reason>.tar.gz`,
  打包附件落盘目录(`asset_attachment_dir`,默认 /data/asset-attachments)全部文件。
  附件包与 .dump 同进退:轮替删 .dump 时同删附件包,无对应 .dump 的孤儿附件包
  (preupgrade 除外)也在轮替时清掉;还原 .dump 后如有对应附件包则解回附件目录,
  解包前先把现有附件目录移走备份(防覆盖丢档)。无附件目录或目录为空时跳过打包
  但记日志,备份本身不失败;附件打包/解包失败亦不推翻资料库备份/还原的主流程
  (打包失败只记警告,解包失败则尝试恢复原附件目录后报错)。
"""

import logging
import os
import re
import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import unquote, urlsplit

from app.core.config import settings

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^backup_(\d{8}_\d{6})_([a-z]+)\.dump$")
_TAR_RE = re.compile(r"^backup_(\d{8}_\d{6})_([a-z]+)\.tar\.gz$")

# 附件落盘目录默认值:并行任务 #12 在 Settings 里加的 `asset_attachment_dir`
# 尚未落地时用此默认,不报错。
_DEFAULT_ATTACHMENT_DIR = "/data/asset-attachments"

# pg_restore 进较旧服务器时,新版 pg_dump 写入的跨版本 GUC(如 v17 的 transaction_timeout)
# 会让该笔 SET 失败但资料不受影响。这类「设置参数不认得」是唯一被容忍的错误;
# 其余任何 `pg_restore: error` 都可能代表资料真的没还原完整,一律视为失败。
_IGNORABLE_RESTORE = re.compile(r"unrecognized configuration parameter", re.IGNORECASE)


class BackupError(Exception):
    """备份/还原失败(呼叫端转为 4xx/5xx)。"""


@dataclass(frozen=True, slots=True)
class BackupInfo:
    name: str
    size_bytes: int
    created_at: datetime
    reason: str
    # 附件包(#83):与 .dump 同名的 .tar.gz 是否存在及其大小;无附件包时为 False/None。
    has_attachments: bool = False
    attachment_size_bytes: int | None = None


def _attachment_dir() -> str:
    """附件落盘目录:读 Settings.asset_attachment_dir(#12 新加配置项),
    配置项尚未出现时用默认路径,不报错。"""
    return getattr(settings, "asset_attachment_dir", None) or _DEFAULT_ATTACHMENT_DIR


def attachment_tar_name(dump_name: str) -> str:
    """某份 .dump 对应的附件包档名(同名、后缀换 .tar.gz)。"""
    if not dump_name.endswith(".dump"):
        raise BackupError("非法的备份档名")
    return dump_name[: -len(".dump")] + ".tar.gz"


def _pack_attachments(tar_path: str) -> int | None:
    """把附件目录打包成 tar.gz。回传打包的文件数;无目录/目录为空时
    跳过并记日志、回传 None;打包失败记警告、删掉半成品、不让备份失败。"""
    src = _attachment_dir()
    if not os.path.isdir(src):
        logger.info("备份附件跳过:附件目录不存在(%s)", src)
        return None
    files: list[str] = []
    for root, _dirs, names in os.walk(src):
        for n in names:
            files.append(os.path.join(root, n))
    if not files:
        logger.info("备份附件跳过:附件目录为空(%s)", src)
        return None
    try:
        with tarfile.open(tar_path, "w:gz") as tf:
            for f in files:
                tf.add(f, arcname=os.path.relpath(f, src))
    except OSError as e:
        logger.warning("备份附件打包失败(资料库备份不受影响):%s", e)
        try:
            os.remove(tar_path)
        except OSError:
            pass
        return None
    logger.info("备份附件已打包:%s(%d 个文件)", tar_path, len(files))
    return len(files)


def _check_tar_members(tf: tarfile.TarFile) -> None:
    """附件包成员路径检查:拒绝绝对路径与 `..` 跳出(解包前先验,避免半途失败)。"""
    for m in tf.getmembers():
        if os.path.isabs(m.name) or ".." in m.name.split("/"):
            raise BackupError(f"附件包内含非法路径成员:{m.name}")


def _restore_attachments(tar_path: str) -> int:
    """把附件包解回附件目录。解包前先把现有附件目录整体移走备份
    (同目录加 .pre-restore-<时间戳> 后缀),解包失败则删掉半成品并移回原目录。
    回传解回的文件数。"""
    dest = _attachment_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    # 先验附件包:非法成员在动现有目录之前就拒绝,避免白白移走原目录。
    try:
        with tarfile.open(tar_path, "r:gz") as tf:
            _check_tar_members(tf)
    except (tarfile.TarError, OSError) as e:
        raise BackupError(f"附件包无法读取:{e}") from e
    backup_dir: str | None = None
    if os.path.isdir(dest) and os.listdir(dest):
        backup_dir = f"{dest}.pre-restore-{ts}"
        try:
            shutil.move(dest, backup_dir)
        except OSError as e:
            raise BackupError(f"还原附件前备份现有附件目录失败:{e}") from e
        logger.info("还原附件:现有附件目录已移至 %s", backup_dir)
    try:
        with tarfile.open(tar_path, "r:gz") as tf:
            tf.extractall(dest, filter="data")
    except (tarfile.TarError, OSError) as e:
        try:
            if os.path.isdir(dest):
                shutil.rmtree(dest)
            if backup_dir and os.path.isdir(backup_dir):
                shutil.move(backup_dir, dest)
        except OSError:
            pass
        raise BackupError(f"还原附件失败(已尝试恢复原附件目录):{e}") from e
    count = sum(len(names) for _r, _d, names in os.walk(dest)) if os.path.isdir(dest) else 0
    logger.info("还原附件完成:%s(%d 个文件)", dest, count)
    return count


def _dir() -> str:
    os.makedirs(settings.backup_dir, exist_ok=True)
    return settings.backup_dir


def _db_params() -> dict[str, str]:
    u = urlsplit(settings.database_url)
    return {
        "host": u.hostname or "localhost",
        "port": str(u.port or 5432),
        "user": unquote(u.username or ""),
        "password": unquote(u.password or ""),
        "dbname": u.path.lstrip("/") or "postgres",
    }


def _env(params: dict[str, str]) -> dict[str, str]:
    e = os.environ.copy()
    e["PGPASSWORD"] = params["password"]
    return e


def _path(name: str) -> str:
    # 防止路径穿越:只接受单纯档名
    if os.path.basename(name) != name or not name.endswith(".dump"):
        raise BackupError("非法的备份档名")
    return os.path.join(_dir(), name)


# ── 清单 / 轮替(任何映像可用)──────────────────────────────
def _info(name: str) -> BackupInfo | None:
    m = _NAME_RE.match(name)
    if m is None:
        return None
    full = os.path.join(_dir(), name)
    try:
        st = os.stat(full)
        tar_path = os.path.join(_dir(), attachment_tar_name(name))
        has_att = os.path.exists(tar_path)
        att_size = os.stat(tar_path).st_size if has_att else None
    except OSError:
        return None
    return BackupInfo(
        name=name, size_bytes=st.st_size,
        created_at=datetime.strptime(m.group(1), "%Y%m%d_%H%M%S"),
        reason=m.group(2),
        has_attachments=has_att, attachment_size_bytes=att_size,
    )


def list_backups() -> list[BackupInfo]:
    """最新在前(只列 .dump;附件包是其附属,不单独成条)。"""
    out = [i for f in os.listdir(_dir()) if (i := _info(f)) is not None]
    return sorted(out, key=lambda i: i.name, reverse=True)


def prune(keep: int | None = None) -> list[str]:
    """保留最新 keep 份,删除其余。回传被删档名(含随 .dump 同删的附件包)。"""
    keep = settings.backup_keep if keep is None else keep
    # 升级前备份是退回旧版的依据,每日备份满 30 份也不能把它挤掉
    backups = [b for b in list_backups() if b.reason != "preupgrade"]
    removed = []
    for info in backups[keep:]:
        for path in (os.path.join(_dir(), info.name),
                     os.path.join(_dir(), attachment_tar_name(info.name))):
            try:
                os.remove(path)
                removed.append(os.path.basename(path))
            except OSError:
                pass
    # 孤儿附件包:对应的 .dump 已不在(例如经删除端点只删了 .dump),一并清掉;
    # preupgrade 的附件包与其 .dump 一样由组长自己决定何时删除,不动。
    for f in os.listdir(_dir()):
        m = _TAR_RE.match(f)
        if m is None or m.group(2) == "preupgrade":
            continue
        dump_sibling = os.path.join(_dir(), f[: -len(".tar.gz")] + ".dump")
        if not os.path.exists(dump_sibling):
            try:
                os.remove(os.path.join(_dir(), f))
                removed.append(f)
            except OSError:
                pass
    return removed


def is_valid_dump(path: str) -> bool:
    """custom 格式的 pg_dump 档以魔数 `PGDMP` 开头。"""
    try:
        with open(path, "rb") as f:
            return f.read(5) == b"PGDMP"
    except OSError:
        return False


# ── dump / restore(需 pg_dump/pg_restore,worker 映像)──────
def create_backup(reason: str = "manual") -> BackupInfo:
    """跑 pg_dump 产生一份备份并轮替。回传新备份信息。"""
    reason = reason if reason.isalpha() else "manual"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"backup_{ts}_{reason}.dump"
    path = os.path.join(_dir(), name)
    p = _db_params()
    try:
        subprocess.run(
            ["pg_dump", "-Fc", "-h", p["host"], "-p", p["port"],
             "-U", p["user"], "-d", p["dbname"], "-f", path],
            check=True, env=_env(p), capture_output=True, text=True,
        )
    except FileNotFoundError as e:
        raise BackupError("找不到 pg_dump(需在 worker 映像执行)") from e
    except subprocess.CalledProcessError as e:
        raise BackupError(f"备份失败:{e.stderr or e}") from e
    # 资料库 dump 成功后再打包附件;附件打包失败/无附件只记日志,不推翻本次备份。
    _pack_attachments(os.path.join(_dir(), attachment_tar_name(name)))
    prune()
    info = _info(name)
    if info is None:
        raise BackupError("备份档产生后无法读取")
    return info


def _terminate_other_connections(p: dict[str, str]) -> None:
    """还原前踢掉其他连线,避免 pg_restore 的 DROP 被锁住(尽力而为)。"""
    try:
        import psycopg
        with psycopg.connect(
            host=p["host"], port=int(p["port"]), user=p["user"],
            password=p["password"], dbname=p["dbname"], connect_timeout=5,
        ) as conn:
            conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (p["dbname"],),
            )
            conn.commit()
    except Exception:  # noqa: BLE001 - 尽力而为,失败不阻止还原
        pass


def _classify_restore_stderr(stderr: str) -> list[str]:
    """查看 pg_restore 的 stderr,回传可忽略的警告摘要。

    只有「设置参数不认得」(跨版本 GUC 噪音)被容忍;出现任何其他 `pg_restore: error`
    就掷 BackupError——只凭 returncode==1 分不出「跨版本噪音」与「某张表 COPY 失败」,
    后者若被当成成功,会把资料缺漏报成还原成功。
    """
    warnings: list[str] = []
    for raw in stderr.splitlines():
        s = raw.strip()
        if not s:
            continue
        low = s.lower()
        if "pg_restore: error" in low or "; error while" in low:
            if _IGNORABLE_RESTORE.search(s):
                warnings.append(s)
                continue
            raise BackupError(f"还原时出现非预期错误:{s}")
        if "warning" in low or "errors ignored on restore" in low:
            warnings.append(s)
    return warnings


def restore_backup(name: str) -> list[str]:
    """从指定备份还原(先验证档头)。回传可忽略的警告摘要;呼叫端负责事后强制重新登录。"""
    path = _path(name)
    if not os.path.exists(path):
        raise BackupError("找不到备份档")
    if not is_valid_dump(path):
        raise BackupError("这不是有效的备份档(格式不符),已拒绝还原")
    p = _db_params()
    _terminate_other_connections(p)
    try:
        proc = subprocess.run(
            ["pg_restore", "--clean", "--if-exists", "--no-owner", "--no-privileges",
             "-h", p["host"], "-p", p["port"], "-U", p["user"], "-d", p["dbname"], path],
            check=False, env=_env(p), capture_output=True, text=True,
        )
    except FileNotFoundError as e:
        raise BackupError("找不到 pg_restore(需在 worker 映像执行)") from e
    # returncode>1 直接失败;==1 需逐行判别是「可忽略的跨版本噪音」还是真正的资料错误。
    if proc.returncode > 1:
        raise BackupError(f"还原失败:{proc.stderr or proc.returncode}")
    warnings = _classify_restore_stderr(proc.stderr) if proc.returncode == 1 else []
    if warnings:
        logger.warning("pg_restore 完成但有可忽略的警告:%s", " | ".join(warnings))
    # 资料库还原成功后,有对应附件包则解回附件目录;无附件包只记日志。
    tar_path = os.path.join(_dir(), attachment_tar_name(name))
    if os.path.exists(tar_path):
        _restore_attachments(tar_path)
    else:
        logger.info("还原 %s:无对应附件包,仅还原资料库", name)
    return warnings


def save_uploaded(name_hint: str, data: bytes) -> str:
    """把上传的备份档写入备份目录,先验证格式;回传实际档名。非法则拒绝不落地。"""
    if data[:5] != b"PGDMP":
        raise BackupError("这不是有效的备份档(格式不符)")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"backup_{ts}_upload.dump"
    with open(os.path.join(_dir(), name), "wb") as f:
        f.write(data)
    return name
