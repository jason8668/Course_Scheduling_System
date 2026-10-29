"""公共假日自动同步 + 中国传统节日。

来源:
- 公共假日走国内接口,主用 timor.tech,失败时退到 jiejiariapi。
  timor 回 {"code": 0, "holiday": {"2026-01-01": {"holiday": true, "name": "元旦", ...}}}:
  holiday=true 才是放假, false 是调休上班日,不建事件。
  jiejiariapi 回 {"2026-01-01": {"name": "元旦", "isOffDay": true, ...}}:
  isOffDay=true 才是放假;整年回 "Year not found" 表示该年还没公布。
- 传统节日本地算,不走网络:农历节日用 sxtwl 换算,清明/冬至是节气,
  同样用 sxtwl 的节气日。学校在浙江,小年按南方腊月廿四。

写入规则(幂等,可反复跑):
- 只管理自己建的事件: note 以“系统自动同步”开头。手动建的校历事件
  一律不动;同步时先删本学期的同类自动事件再重建,不会越删越多。
- 公共假日事件: event_type=holiday, scope=school, 单日, 课时统计
  的 _is_holiday 本来就认这类事件,所以放假那天自动扣课,无需另改口径。
- 传统节日事件: event_type=other, scope=school, 单日, 只展示不扣课。
  若某传统节日当天已是公共假日(如春节、清明),不再重复建一个同名事件,
  校历上已有放假事件标着那天,避免冗余。
- 没公布 / 接口失败时创建与同步都不报错:公共假日保持原样不动,
  传统节日照常建,下一次每日同步再试。创建学期绝不因接口失败而失败。

触发点:
- 学期创建/复制: API 层把单学期同步任务丢进 ops 队列(worker 跑),
  Redis 不可用时只记日志,不影响创建返回;测试环境没有 worker 时
  同样不影响创建,手动同步端点与每日任务会补上。
- 每日任务: workers/holiday_sync_job, 由 scheduler 每天续期一次,
  扫全部有起止日期的学期,逐年重跑。
"""

import logging
from datetime import date, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.calendar import SchoolCalendarEvent
from app.models.semester import Semester

logger = logging.getLogger(__name__)

AUTO_NOTE_PREFIX = "系统自动同步"
HOLIDAY_NOTE = "系统自动同步：公共假日"
FESTIVAL_NOTE = "系统自动同步：传统节日"

TIMOR_URL = "https://timor.tech/api/holiday/year/{year}"
JIEJIARIAPI_URL = "https://api.jiejiariapi.com/v1/holidays/{year}"
FETCH_TIMEOUT = 5.0

# sxtwl 的节气序号: 0=冬至, 1=小寒, 2=大寒, 3=立春, 4=雨水, 5=惊蛰,
# 6=春分, 7=清明, 8=谷雨, 9=立夏, 10=小满, 11=芒种, 12=夏至, 13=小暑,
# 14=大暑, 15=立秋, 16=处暑, 17=白露, 18=秋分, 19=寒露, 20=霜降,
# 21=立冬, 22=小雪, 23=大雪。本模块只取清明(7)与冬至(0)。
_JIEQI_NAMES = [
    "冬至",
    "小寒",
    "大寒",
    "立春",
    "雨水",
    "惊蛰",
    "春分",
    "清明",
    "谷雨",
    "立夏",
    "小满",
    "芒种",
    "夏至",
    "小暑",
    "大暑",
    "立秋",
    "处暑",
    "白露",
    "秋分",
    "寒露",
    "霜降",
    "立冬",
    "小雪",
    "大雪",
]

# (农历月, 农历日, 节日名);小年按南方腊月廿四。
_LUNAR_FESTIVALS = [
    (1, 1, "春节"),
    (1, 15, "元宵"),
    (5, 5, "端午"),
    (7, 7, "七夕"),
    (8, 15, "中秋"),
    (9, 9, "重阳"),
    (12, 8, "腊八"),
    (12, 24, "小年"),
]


def _parse_timor(payload) -> dict[date, str] | None:
    """timor 成功回放假映射,格式不对回 None(由调用方决定是否退到备用接口)。"""
    if not isinstance(payload, dict):
        return None
    if payload.get("code") != 0:
        return None
    raw = payload.get("holiday")
    if not isinstance(raw, dict):
        return None
    out: dict[date, str] = {}
    for key, info in raw.items():
        if not isinstance(info, dict) or not info.get("holiday"):
            continue
        try:
            out[date.fromisoformat(str(key))] = str(info.get("name") or "公共假日")
        except ValueError:
            continue
    return out


def _parse_jiejiariapi(payload) -> dict[date, str] | None:
    """jiejiariapi 成功回放假映射;回 "Year not found" 时调用方另行处理。"""
    if not isinstance(payload, dict):
        return None
    out: dict[date, str] = {}
    for key, info in payload.items():
        if not isinstance(info, dict) or not info.get("isOffDay"):
            continue
        try:
            out[date.fromisoformat(str(key))] = str(info.get("name") or "公共假日")
        except ValueError:
            continue
    return out


def fetch_public_holidays(year: int) -> tuple[str, dict[date, str]]:
    """抓某年公共假日。回 (状态, 放假映射)。

    状态: "ok" 已拿到数据(可能为空 dict,代表已公布但该年无放假——
    实际不会发生,仅作语义区分); "unpublished" 接口明确说该年还没公布;
    "failed" 两接口都拿不到可用数据(网络/CF 拦截/格式异常等)。
    """
    try:
        resp = httpx.get(TIMOR_URL.format(year=year), timeout=FETCH_TIMEOUT)
        parsed = _parse_timor(resp.json()) if resp.status_code == 200 else None
        if parsed is not None:
            return "ok", parsed
    except Exception as exc:  # noqa: BLE001 - 接口失败走备用,原因只记日志
        logger.warning("公共假日 timor 接口失败(%s 年):%s", year, exc)
    try:
        resp = httpx.get(JIEJIARIAPI_URL.format(year=year), timeout=FETCH_TIMEOUT)
        if resp.status_code == 200:
            text = resp.text.strip()
            if text == "Year not found":
                return "unpublished", {}
            parsed = _parse_jiejiariapi(resp.json())
            if parsed is not None:
                return "ok", parsed
    except Exception as exc:  # noqa: BLE001 - 备用接口也失败,同步方保持原样
        logger.warning("公共假日备用接口失败(%s 年):%s", year, exc)
    return "failed", {}


def traditional_festivals(year: int) -> list[tuple[date, str]]:
    """某公历年内要标的传统节日(日期, 节日名)。sxtwl 未装时回空,不报错。"""
    try:
        import sxtwl
    except ImportError:
        logger.warning("传统节日计算需要 sxtwl,未安装则跳过(%s 年)", year)
        return []
    out: dict[date, str] = {}
    # 农历节日:腊八/小年在公历 1 月的,属于上一个农历年,故农历年取 year-1 与 year
    for lunar_year in (year - 1, year):
        for month, day, name in _LUNAR_FESTIVALS:
            try:
                solar = sxtwl.fromLunar(lunar_year, month, day)
            except Exception:  # noqa: BLE001 - 某农历月不存在时跳过该节日
                continue
            d = date(solar.getSolarYear(), solar.getSolarMonth(), solar.getSolarDay())
            if d.year == year:
                out[d] = name
    # 节气:逐日扫该年,只要清明与冬至
    d = date(year, 1, 1)
    while d.year == year:
        day = sxtwl.fromSolar(d.year, d.month, d.day)
        if day.hasJieQi():
            name = _JIEQI_NAMES[day.getJieQi()]
            if name in ("清明", "冬至"):
                out[d] = name
        d += timedelta(days=1)
    return sorted(out.items())


def _auto_events(db: Session, semester_id: int, year: int, note: str) -> list[SchoolCalendarEvent]:
    rows = db.scalars(
        select(SchoolCalendarEvent).where(
            SchoolCalendarEvent.semester_id == semester_id,
            SchoolCalendarEvent.note == note,
        )
    ).all()
    return [r for r in rows if r.start_date.year == year]


def sync_year(
    db: Session,
    semester: Semester,
    year: int,
    *,
    fetcher=None,
) -> dict:
    """同步某学期某年的假日+传统节日。只删重建本年的自动事件,手动事件不动。"""
    fetch = fetcher or fetch_public_holidays
    try:
        status, holidays = fetch(year)
    except Exception as exc:  # noqa: BLE001 - 测试用 fetcher 抛错也按失败处理
        logger.warning("公共假日抓取抛错(%s 年):%s", year, exc)
        status, holidays = "failed", {}
    # 传统节日:与公共假日重日的跳过(放假事件已标那天,不重复)
    festivals = (
        [(d, name) for d, name in traditional_festivals(year) if d not in holidays]
        if status == "ok"
        else traditional_festivals(year)
    )
    for row in _auto_events(db, semester.id, year, FESTIVAL_NOTE):
        db.delete(row)
    for d, name in festivals:
        db.add(
            SchoolCalendarEvent(
                semester_id=semester.id,
                title=name,
                event_type="other",
                scope_type="school",
                scope_id=None,
                start_date=d,
                end_date=d,
                note=FESTIVAL_NOTE,
            )
        )
    public_count = None
    if status == "ok":
        for row in _auto_events(db, semester.id, year, HOLIDAY_NOTE):
            db.delete(row)
        for d, name in sorted(holidays.items()):
            db.add(
                SchoolCalendarEvent(
                    semester_id=semester.id,
                    title=name,
                    event_type="holiday",
                    scope_type="school",
                    scope_id=None,
                    start_date=d,
                    end_date=d,
                    note=HOLIDAY_NOTE,
                )
            )
        public_count = len(holidays)
    db.commit()
    return {
        "year": year,
        "status": status,
        "public_holidays": public_count,
        "festivals": len(festivals),
    }


def semester_years(semester: Semester) -> list[int]:
    """学期覆盖的公历年;没填起止日期时回空(同步方跳过,等填了日期再说)。"""
    if semester.start_date is None or semester.end_date is None:
        return []
    if semester.end_date < semester.start_date:
        return []
    return list(range(semester.start_date.year, semester.end_date.year + 1))


def sync_semester(db: Session, semester: Semester, *, fetcher=None) -> list[dict]:
    """同步某学期全部年份。没日期的学期回空,不报错。"""
    return [sync_year(db, semester, y, fetcher=fetcher) for y in semester_years(semester)]


def sync_all_semesters(db: Session, *, fetcher=None) -> list[dict]:
    """每日任务用:扫全部学期逐个同步,单个学期失败不影响其他学期。"""
    results: list[dict] = []
    for semester in db.scalars(select(Semester)).all():
        try:
            for item in sync_semester(db, semester, fetcher=fetcher):
                results.append({"semester_id": semester.id, **item})
        except Exception as exc:  # noqa: BLE001 - 单学期失败只记日志,继续扫
            logger.warning("假日同步学期 %s 失败:%s", semester.id, exc)
    return results


def enqueue_semester_sync(semester_id: int) -> None:
    """学期创建/复制后把单学期同步丢进 ops 队列;Redis 不可用时只记日志。"""
    try:
        from app.workers.holiday_sync_job import holiday_sync_semester_job
        from app.workers.queue import ops_queue

        ops_queue.enqueue(
            holiday_sync_semester_job,
            semester_id,
            job_timeout=120,
        )
    except Exception as exc:  # noqa: BLE001 - 创建绝不因此失败,每日任务会补
        logger.warning("假日同步任务入队失败(学期 %s):%s", semester_id, exc)


def is_holiday_on(
    db: Session,
    semester_id: int,
    on: date,
    period_no: int,
    grades: set[int],
    class_ids: set[int],
) -> bool:
    """提醒用:某天某节是否放假(口径与课时统计一致,只看一次性放假事件)。"""
    rows = db.scalars(
        select(SchoolCalendarEvent).where(
            SchoolCalendarEvent.semester_id == semester_id,
            SchoolCalendarEvent.event_type == "holiday",
            SchoolCalendarEvent.weekly_recurring.is_(False),
            SchoolCalendarEvent.start_date <= on,
            SchoolCalendarEvent.end_date >= on,
        )
    ).all()
    for ev in rows:
        if ev.period_start is not None and not (
            ev.period_start <= period_no <= (ev.period_end or ev.period_start)
        ):
            continue
        if ev.scope_type == "school":
            return True
        if ev.scope_type == "grade" and ev.scope_id in grades:
            return True
        if ev.scope_type == "class" and ev.scope_id in class_ids:
            return True
    return False
