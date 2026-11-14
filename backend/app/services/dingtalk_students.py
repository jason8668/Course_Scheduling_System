"""从钉钉导入学生名单(KW-01 扩展):部门树、成员预览、确认导入。

学生与家长/老师的区分只认家校通讯录 2.0 的身份接口
POST /topapi/edu/user/get,回 role=teacher/guardian/student(见钉钉开放平台「获取人员身份详情」,
权限:钉钉教育家校通讯录读)。企业通讯录标准接口
/topapi/v2/user/list 不带角色字段,分不出学生与家长/老师,
所以预览与导入确认时都以 edu 身份接口为准:只有 role=student
的行可导入,家长/老师/身份未确认的行一律不进档案,绝不静默
把家长导成学生。

字段口径(钉钉只给姓名、手机号、部门、学号):
- 姓名 → 姓名;学号 → 学号(家校身份接口学生角色自带,学校若未在
  钉钉维护学号则留空,预览标“待补”,管理员填好才能勾选导入)。
- 性别钉钉不提供,导入后为空,以后在档案里补或用 Excel 补。
- 学生本人的手机号只在预览里展示供核对,不写入任何字段(学生
  档案没有电话字段,也不设家长联系)。
- 部门 → 班级:按名匹配系统已有班级(同名唯一),匹配不上时管理
  员在界面上选班级,不猜。

去重与 Excel 导入同一口径:同学期同学号重复导入为更新;同名同班
的跳过不新建;返回新增/更新/跳过数,记审计日志。
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.basedata import ClassUnit
from app.models.exam_foundation import Student
from app.services import settings as app_settings
from app.services.dingtalk_app import DingTalkAppClient

logger = logging.getLogger(__name__)

ROLE_STUDENT = "student"
ROLE_GUARDIAN = "guardian"
ROLE_TEACHER = "teacher"
ROLE_UNKNOWN = "unknown"

_GRADE_CN = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}
_PERMISSION_ERRCODES = {40008, 60011, 60012, 50002, 41008}
_MAX_DEPT_DEPTH = 10
_MAX_MEMBERS = 5000
_ROLE_WORKERS = 8


class DingTalkNotConfiguredError(Exception):
    """钉钉企业应用三件套未配。"""


class DingTalkPermissionError(Exception):
    """钉钉接口报权限不足;permission 是要开通的权限名。"""

    def __init__(self, permission: str, detail: str = "") -> None:
        super().__init__(detail or permission)
        self.permission = permission
        self.detail = detail


class DingTalkApiError(Exception):
    """钉钉接口调用失败(非权限原因)。"""


def _is_permission_error(exc: Exception) -> bool:
    text = str(exc)
    if "权限" in text or "permission" in text.lower():
        return True
    codes = {int(n) for n in re.findall(r"\b(\d{5})\b", text)}
    return bool(codes & _PERMISSION_ERRCODES)


def _wrap(exc: Exception, permission: str) -> Exception:
    if _is_permission_error(exc):
        return DingTalkPermissionError(permission, str(exc))
    return DingTalkApiError(str(exc))


def get_client(db: Session) -> DingTalkAppClient:
    """取已配置的企业应用客户端;未配时掷 DingTalkNotConfiguredError。"""
    cfg = app_settings.dingtalk_app_config(db)
    if not cfg.configured:
        raise DingTalkNotConfiguredError(
            "钉钉企业应用未配置,请管理员在系统管理里填写 appKey、应用密钥与 agentId"
        )
    return DingTalkAppClient(cfg.app_key, cfg.app_secret, cfg.agent_id)


def build_dept_tree(client: DingTalkAppClient) -> list[dict]:
    """从根部门(1)递归取子部门,建成树;返回 [{dept_id, name, parent_id, children}]。"""
    try:
        return _build_dept_tree(client, 1, set(), 0)
    except DingTalkPermissionError:
        raise
    except DingTalkApiError:
        raise
    except Exception as exc:  # noqa: BLE001 - 钉钉层面的失败统一转成语义错误
        raise _wrap(exc, "通讯录读取") from exc


def _build_dept_tree(
    client: DingTalkAppClient, dept_id: int, visited: set[int], depth: int
) -> list[dict]:
    if dept_id in visited or depth > _MAX_DEPT_DEPTH:
        return []
    visited.add(dept_id)
    children = client.list_sub_departments(dept_id)
    tree = []
    for child in children:
        child_id = int(child["dept_id"])
        tree.append({
            "dept_id": child_id,
            "name": str(child.get("name") or ""),
            "parent_id": dept_id,
            "children": _build_dept_tree(client, child_id, visited, depth + 1),
        })
    return tree


def list_all_department_users(
    client: DingTalkAppClient, dept_id: int
) -> list[dict]:
    """取某部门全部直属成员详情(分页拉满);失败掷语义错误。"""
    members: list[dict] = []
    cursor = 0
    try:
        while True:
            result = client.list_department_users(dept_id, cursor=cursor, size=100)
            members.extend(result.get("list") or [])
            if len(members) > _MAX_MEMBERS:
                raise DingTalkApiError("钉钉部门成员过多,超过 5000 人上限")
            if not result.get("has_more"):
                break
            cursor = int(result.get("next_cursor") or 0)
    except (DingTalkPermissionError, DingTalkApiError):
        raise
    except Exception as exc:  # noqa: BLE001 - 见 build_dept_tree
        raise _wrap(exc, "通讯录读取") from exc
    return members


def _extract_student_no(result: dict) -> str:
    """从身份接口结果里取学号:顶层 student_no 优先,其次嵌套属性。"""
    if result.get("student_no"):
        return str(result["student_no"]).strip()
    for key in ("attrs", "ext", "attributes", "extra"):
        nested = result.get(key)
        if isinstance(nested, dict) and nested.get("student_no"):
            return str(nested["student_no"]).strip()
        if isinstance(nested, str):
            try:
                import json

                parsed = json.loads(nested)
            except (ValueError, TypeError):
                continue
            if isinstance(parsed, dict) and parsed.get("student_no"):
                return str(parsed["student_no"]).strip()
    return ""


def _fetch_roles(
    client: DingTalkAppClient, class_id: int, userids: list[str]
) -> tuple[dict[str, tuple[str, str]], list[tuple[str, Exception]]]:
    """并发取一批成员的家校身份;回 ({userid: (role, student_no)}, [(userid, exc)])。

    单人失败不拖垮整批,记为身份未确认;呼叫端据成功数决定是否整体失败。
    """
    roles: dict[str, tuple[str, str]] = {}
    failures: list[tuple[str, Exception]] = []

    def _one(userid: str) -> tuple[str, tuple[str, str] | None, Exception | None]:
        try:
            result = client.get_edu_user(class_id, userid)
            return userid, (str(result.get("role") or ""), _extract_student_no(result)), None
        except Exception as exc:  # noqa: BLE001 - 单人失败只记下来
            return userid, None, exc

    with ThreadPoolExecutor(max_workers=_ROLE_WORKERS) as pool:
        for userid, role_no, exc in pool.map(_one, userids):
            if role_no is not None:
                roles[userid] = role_no
            else:
                failures.append((userid, exc))  # type: ignore[arg-type]
    return roles, failures


def _parse_grade(text: str) -> int | None:
    """从“七年级”“十二年级”这类字串里解析年级数字;解析不出回 None。"""
    m = re.search(r"([一二三四五六七八九十]+)年级", text or "")
    if not m:
        return None
    cn = m.group(1)
    if len(cn) == 1:
        return _GRADE_CN.get(cn)
    if cn.startswith("十"):
        return 10 + (_GRADE_CN.get(cn[1:], 0) if len(cn) > 1 else 0)
    return None


def suggest_class(
    db: Session, semester_id: int, dept_name: str, dept_path: list[str]
) -> ClassUnit | None:
    """部门名 → 系统班级:同名唯一,按名匹配;匹配不上回 None,不猜。

    先精确匹配,再取部门名后缀匹配(部门名常带年级前缀,如“七年级 1班”);
    多个后缀都对得上时取名字最长的(如“11班”优先于“1班”);
    能从部门路径解析出年级且与班级年级不符时不建议,等管理员选。
    """
    classes = db.scalars(
        select(ClassUnit).where(ClassUnit.semester_id == semester_id)
    ).all()
    if not classes:
        return None
    norm = lambda s: (s or "").replace(" ", "").replace("　", "")
    dept_norm = norm(dept_name)
    exact = [c for c in classes if norm(c.name) == dept_norm]
    if len(exact) == 1:
        return _grade_checked(exact[0], dept_path)
    cands = [c for c in classes if norm(c.name) and dept_norm.endswith(norm(c.name))]
    if not cands:
        return None
    longest = max(len(norm(c.name)) for c in cands)
    top = [c for c in cands if len(norm(c.name)) == longest]
    if len(top) != 1:
        return None
    return _grade_checked(top[0], dept_path)


def _grade_checked(cls: ClassUnit, dept_path: list[str]) -> ClassUnit | None:
    grade = None
    for part in dept_path or []:
        grade = _parse_grade(part)
        if grade is not None:
            break
    if grade is not None and cls.grade != grade:
        return None
    return cls


def preview_department(
    db: Session,
    client: DingTalkAppClient,
    semester_id: int,
    dept_id: int,
    dept_path: list[str],
    class_unit_id: int | None = None,
) -> dict:
    """某钉钉部门的导入预览:成员分角色、可导入学生行、建议班级。

    只有 role=student 的行可导入;家长/老师只计数不进列表;身份未确认
    的行单独列出、不可导入。exists 按目标班级算:有目标班级时才判同名。
    """
    members = list_all_department_users(client, dept_id)
    dept_name = (dept_path or [""])[-1]
    suggested = suggest_class(db, semester_id, dept_name, dept_path or [])
    target_id = class_unit_id if class_unit_id is not None else (
        suggested.id if suggested else None
    )
    target_name = None
    if target_id is not None:
        target = db.get(ClassUnit, target_id)
        target_name = target.name if target else None

    userids = [str(m.get("userid") or "") for m in members if m.get("userid")]
    roles, failures = _fetch_roles(client, dept_id, userids)
    if userids and not roles:
        first_exc = failures[0][1] if failures else RuntimeError("钉钉身份接口无返回")
        raise _wrap(first_exc, "钉钉教育家校通讯录读")
    failed_ids = {uid for uid, _ in failures}

    by_student_no = {
        s.student_no: s
        for s in db.scalars(
            select(Student).where(Student.semester_id == semester_id)
        ).all()
        if s.student_no
    }
    same_names: set[str] = set()
    if target_id is not None:
        same_names = {
            s.name
            for s in db.scalars(
                select(Student).where(
                    Student.semester_id == semester_id,
                    Student.class_unit_id == target_id,
                )
            ).all()
        }

    counts = {"student": 0, "guardian": 0, "teacher": 0, "unknown": 0}
    students: list[dict] = []
    unconfirmed: list[dict] = []
    for m in members:
        userid = str(m.get("userid") or "")
        name = str(m.get("name") or "")
        mobile = (str(m.get("mobile") or "").strip()) or None
        if not userid or userid in failed_ids or userid not in roles:
            counts["unknown"] += 1
            unconfirmed.append({
                "userid": userid, "name": name, "mobile": mobile,
                "reason": "钉钉身份接口未返回角色,无法确认是学生还是家长/老师",
            })
            continue
        role, student_no = roles[userid]
        if role == ROLE_STUDENT:
            counts["student"] += 1
            if student_no and student_no in by_student_no:
                exists = "update"
            elif target_id is not None and name in same_names:
                exists = "same_name"
            else:
                exists = "new"
            students.append({
                "userid": userid, "name": name, "mobile": mobile, "role": role,
                "student_no": student_no or None,
                "student_no_missing": not student_no,
                "exists": exists,
                "missing_fields": ["学号"] if not student_no else [],
            })
        elif role == ROLE_GUARDIAN:
            counts["guardian"] += 1
        elif role == ROLE_TEACHER:
            counts["teacher"] += 1
        else:
            counts["unknown"] += 1
            unconfirmed.append({
                "userid": userid, "name": name, "mobile": mobile,
                "reason": f"钉钉返回未知角色「{role}」,无法确认是学生",
            })
    return {
        "dept_id": dept_id,
        "dept_name": dept_name,
        "dept_path": list(dept_path or []),
        "total_members": len(members),
        "student_count": counts["student"],
        "guardian_count": counts["guardian"],
        "teacher_count": counts["teacher"],
        "unknown_count": counts["unknown"],
        "suggested_class_unit_id": suggested.id if suggested else None,
        "suggested_class_name": suggested.name if suggested else None,
        "target_class_unit_id": target_id,
        "target_class_name": target_name,
        "students": students,
        "unconfirmed": unconfirmed,
    }


def import_from_dingtalk(
    db: Session,
    client: DingTalkAppClient,
    semester_id: int,
    dept_id: int,
    class_unit_id: int,
    rows: list[dict],
) -> dict:
    """确认导入:先逐行校验,再重查身份(只认 role=student),最后写入。

    校验不过(学号待补/学号重复)零写入;身份重查全部失败时掷错、零写入;
    单个非学生/身份未确认的行计入跳过,不写档案。
    """
    cls = db.get(ClassUnit, class_unit_id)
    if cls is None or cls.semester_id != semester_id:
        return {"created": 0, "updated": 0, "skipped": 0, "skipped_detail": [],
                "errors": ["班级不存在或不在本学期"]}
    if not rows:
        return {"created": 0, "updated": 0, "skipped": 0, "skipped_detail": [],
                "errors": ["未勾选任何学生"]}
    errors: list[str] = []
    seen_no: set[str] = set()
    cleaned: list[dict] = []
    for row in rows:
        name = str(row.get("name") or "").strip()
        student_no = str(row.get("student_no") or "").strip()
        userid = str(row.get("userid") or "")
        if not name:
            errors.append("有一行姓名为空,请核对")
            continue
        if not student_no:
            errors.append(f"「{name}」学号待补,请先在预览里填好学号")
            continue
        if student_no in seen_no:
            errors.append(f"学号「{student_no}」在本次勾选里重复")
            continue
        seen_no.add(student_no)
        cleaned.append({"userid": userid, "name": name, "student_no": student_no})
    if errors:
        return {"created": 0, "updated": 0, "skipped": 0, "skipped_detail": [],
                "errors": errors}

    # 导入确认时重查身份:前端送什么都只认钉钉身份接口的 role。
    userids = [r["userid"] for r in cleaned if r["userid"]]
    roles, failures = _fetch_roles(client, dept_id, userids)
    if userids and not roles:
        first_exc = failures[0][1] if failures else RuntimeError("钉钉身份接口无返回")
        raise _wrap(first_exc, "钉钉教育家校通讯录读")

    by_student_no = {
        s.student_no: s
        for s in db.scalars(
            select(Student).where(Student.semester_id == semester_id)
        ).all()
        if s.student_no
    }
    same_names = {
        s.name
        for s in db.scalars(
            select(Student).where(
                Student.semester_id == semester_id,
                Student.class_unit_id == class_unit_id,
            )
        ).all()
    }

    created = 0
    updated = 0
    skipped = 0
    skipped_detail: list[str] = []
    for row in cleaned:
        role_no = roles.get(row["userid"])
        if role_no is None or role_no[0] != ROLE_STUDENT:
            skipped += 1
            skipped_detail.append(f"{row['name']}（钉钉身份不是学生，已跳过）")
            continue
        student = by_student_no.get(row["student_no"])
        if student is not None:
            student.name = row["name"]
            student.class_unit_id = class_unit_id
            updated += 1
            continue
        if row["name"] in same_names:
            skipped += 1
            skipped_detail.append(f"{row['name']}（同名学生已在该班，已跳过）")
            continue
        student = Student(
            semester_id=semester_id,
            class_unit_id=class_unit_id,
            student_no=row["student_no"],
            name=row["name"],
            gender=None,
            status="在读",
            exam_no=None,
        )
        db.add(student)
        db.flush()
        by_student_no[row["student_no"]] = student
        same_names.add(row["name"])
        created += 1
    db.commit()
    return {
        "created": created, "updated": updated, "skipped": skipped,
        "skipped_detail": skipped_detail, "errors": [],
    }
