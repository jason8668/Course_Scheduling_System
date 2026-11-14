"""考务地基 API(KW-01~07):学生档案、导入导出、异动、分值、考号。

挂在 /api/exam 下,路由里写相对路径。写接口只允许 admin/director。
所有写操作与导出都记审计。
"""

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.user import Role, User
from app.schemas.exam_students import (
    DingTalkDeptOut,
    DingTalkImportIn,
    DingTalkImportResultOut,
    DingTalkPreviewIn,
    DingTalkPreviewOut,
    ExamNumberGenerateIn,
    ExamNumberGenerateOut,
    ExamNumberRuleOut,
    ExamNumberRulePut,
    ImportResultOut,
    StatusChangeListOut,
    StudentCreate,
    StudentListOut,
    StudentOut,
    StudentStatusChangeIn,
    StatusChangeListOut,
    StudentUpdate,
    SubjectSettingsOut,
    SubjectSettingsPut,
)
from app.services import dingtalk_students
from app.services import exam_students as svc
from app.services.exam_audit import log_exam_action
from app.services.exam_scopes import can_manage_students

router = APIRouter(tags=["exam"])

writer = require_roles(Role.admin, Role.director)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _require_can_manage(db: Session, user: User) -> None:
    if not can_manage_students(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "权限不足")


# ── 学生列表/新增 ──────────────────────────────
@router.get("/students", response_model=StudentListOut)
def list_students(
    semester_id: int = Query(...),
    grade: int | None = None,
    class_unit_id: int | None = None,
    q: str | None = None,
    status: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    rows, total = svc.list_students(
        db, user, semester_id, grade, class_unit_id, q, status, limit, offset
    )
    return StudentListOut(
        items=[svc.to_student_out(db, s) for s in rows],
        total=total,
    )


@router.post("/students", response_model=StudentOut, status_code=status.HTTP_201_CREATED)
def create_student(
    body: StudentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
) -> StudentOut:
    _require_can_manage(db, user)
    student = svc.create_student(
        db, body.semester_id, body.class_unit_id, body.student_no,
        body.name, body.gender, body.status, body.exam_no,
    )
    log_exam_action(
        db, user, "exam_student_create",
        target_type="exam_student", target_id=student.id,
        detail=f"新增学生{student.name}({student.student_no})",
    )
    db.commit()
    return svc.to_student_out(db, student)


# ── 模板/导入/导出(静态路由须在 /students/{id} 之前注册) ──
@router.get("/students/template")
def download_template(
    db: Session = Depends(get_db),
    user: User = Depends(writer),
) -> Response:
    _require_can_manage(db, user)
    return Response(
        content=svc.build_student_template(),
        media_type=XLSX_MIME,
        headers={"Content-Disposition": 'attachment; filename="students_template.xlsx"'},
    )


@router.post("/students/import", response_model=ImportResultOut)
async def import_students(
    semester_id: int = Query(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(writer),
) -> ImportResultOut:
    _require_can_manage(db, user)
    content = await file.read()
    try:
        result = svc.import_students(db, semester_id, content)
    except Exception:
        db.rollback()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "无法读取档案,请确认为有效的 Excel 档"
        ) from None
    if not result["errors"]:
        log_exam_action(
            db, user, "exam_student_import",
            target_type="semester", target_id=semester_id,
            detail=f"导入学生:新增{result['created']}人,更新{result['updated']}人",
        )
        db.commit()
    return ImportResultOut(**result)


@router.get("/students/export")
def export_students(
    semester_id: int = Query(...),
    grade: int | None = None,
    class_unit_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
) -> Response:
    rows, _total = svc.list_students(
        db, user, semester_id, grade, class_unit_id,
        limit=100000, offset=0,
    )
    data = svc.build_student_export(db, rows)
    log_exam_action(
        db, user, "exam_student_export",
        target_type="semester", target_id=semester_id,
        detail=f"导出学生名单{len(rows)}人",
    )
    db.commit()
    return Response(
        content=data,
        media_type=XLSX_MIME,
        headers={"Content-Disposition": 'attachment; filename="students_export.xlsx"'},
    )


# ── 从钉钉导入(静态路由须在 /students/{id} 之前注册) ──
def _dingtalk_client_or_400(db: Session):
    try:
        return dingtalk_students.get_client(db)
    except dingtalk_students.DingTalkNotConfiguredError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def _dingtalk_error_to_http(exc: Exception) -> HTTPException:
    if isinstance(exc, dingtalk_students.DingTalkPermissionError):
        return HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"钉钉调用失败:{exc.detail}。请学校钉钉管理员给应用开通「{exc.permission}」权限。",
        )
    return HTTPException(status.HTTP_502_BAD_GATEWAY, f"钉钉调用失败:{exc}")


@router.get("/students/dingtalk/departments", response_model=list[DingTalkDeptOut])
def dingtalk_departments(
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    """钉钉部门树(从根部门递归);未配应用回 400,钉钉报错回 502 并明示缺什么权限。"""
    _require_can_manage(db, user)
    try:
        client = _dingtalk_client_or_400(db)
        return dingtalk_students.build_dept_tree(client)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - 钉钉错误原文转给管理员看
        raise _dingtalk_error_to_http(exc) from exc


@router.post("/students/dingtalk/preview", response_model=DingTalkPreviewOut)
def dingtalk_preview(
    body: DingTalkPreviewIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    """某钉钉部门的导入预览:成员分角色、可导入学生行、建议班级。"""
    _require_can_manage(db, user)
    try:
        client = _dingtalk_client_or_400(db)
        return dingtalk_students.preview_department(
            db, client, body.semester_id, body.dept_id, body.dept_path,
            body.class_unit_id,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - 见上
        raise _dingtalk_error_to_http(exc) from exc


@router.post("/students/dingtalk/import", response_model=DingTalkImportResultOut)
def dingtalk_import(
    body: DingTalkImportIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    """从钉钉确认导入:重查身份后写入;只认 role=student 的行。"""
    _require_can_manage(db, user)
    try:
        client = _dingtalk_client_or_400(db)
        result = dingtalk_students.import_from_dingtalk(
            db, client, body.semester_id, body.dept_id, body.class_unit_id,
            [s.model_dump() for s in body.students],
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - 见上
        raise _dingtalk_error_to_http(exc) from exc
    if not result["errors"]:
        log_exam_action(
            db, user, "exam_student_dingtalk_import",
            target_type="semester", target_id=body.semester_id,
            detail=f"从钉钉导入学生:新增{result['created']}人,更新{result['updated']}人,"
                   f"跳过{result['skipped']}人",
        )
        db.commit()
    return DingTalkImportResultOut(**result)


# ── 单个学生 ──────────────────────────────
@router.get("/students/{student_id}", response_model=StudentOut)
def get_student(
    student_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
) -> StudentOut:
    student = svc.get_student_visible(db, user, student_id)
    return svc.to_student_out(db, student)


@router.patch("/students/{student_id}", response_model=StudentOut)
def update_student(
    student_id: int,
    body: StudentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
) -> StudentOut:
    _require_can_manage(db, user)
    student = db.get(svc.Student, student_id)
    if student is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到学生")
    student = svc.update_student(
        db, user, student, body.name, body.gender, body.class_unit_id
    )
    log_exam_action(
        db, user, "exam_student_update",
        target_type="exam_student", target_id=student.id,
        detail=f"修改学生{student.name}({student.student_no})档案",
    )
    db.commit()
    return svc.to_student_out(db, student)


@router.post("/students/{student_id}/status", response_model=StudentOut)
def change_status(
    student_id: int,
    body: StudentStatusChangeIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
) -> StudentOut:
    _require_can_manage(db, user)
    student = db.get(svc.Student, student_id)
    if student is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到学生")
    student = svc.change_student_status(
        db, user, student, body.to_status, body.note,
        body.new_class_unit_id, body.change_type,
    )
    log_exam_action(
        db, user, "exam_student_status_change",
        target_type="exam_student", target_id=student.id,
        detail=f"学生{student.name}({student.student_no})状态变更为{student.status}",
    )
    db.commit()
    return svc.to_student_out(db, student)


@router.get("/students/{student_id}/status-changes", response_model=StatusChangeListOut)
def list_status_changes(
    student_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    student = svc.get_student_visible(db, user, student_id)
    return StatusChangeListOut(items=svc.list_status_changes(db, student))


# ── 学科分值 ──────────────────────────────
@router.get("/subject-settings", response_model=SubjectSettingsOut)
def list_subject_settings(
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    return SubjectSettingsOut(items=svc.list_subject_settings(db, user, semester_id))


@router.put("/subject-settings", response_model=SubjectSettingsOut)
def put_subject_settings(
    body: SubjectSettingsPut,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    items = svc.upsert_subject_settings(
        db, user, body.semester_id, [s.model_dump() for s in body.settings]
    )
    log_exam_action(
        db, user, "exam_subject_setting_update",
        target_type="semester", target_id=body.semester_id,
        detail=f"批量更新{len(body.settings)}个科目分值设置",
    )
    db.commit()
    return SubjectSettingsOut(items=items)


# ── 考号规则 ──────────────────────────────
@router.get("/exam-number-rule", response_model=ExamNumberRuleOut)
def get_exam_number_rule(
    semester_id: int = Query(...),
    grade: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    rule = svc.get_exam_number_rule(db, semester_id, grade)
    if rule is None:
        return ExamNumberRuleOut(
            semester_id=semester_id, grade=grade, rule_type="by_student_no"
        )
    return ExamNumberRuleOut.model_validate(rule)


@router.put("/exam-number-rule", response_model=ExamNumberRuleOut)
def put_exam_number_rule(
    body: ExamNumberRulePut,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    rule = svc.upsert_exam_number_rule(db, body.semester_id, body.grade, body.rule_type)
    log_exam_action(
        db, user, "exam_number_rule_update",
        target_type="semester", target_id=body.semester_id,
        detail=f"设置考号规则:年级{body.grade or '全校'}={body.rule_type}",
    )
    db.commit()
    return ExamNumberRuleOut.model_validate(rule)


@router.post("/exam-number-rule/generate", response_model=ExamNumberGenerateOut)
def generate_exam_numbers(
    body: ExamNumberGenerateIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    generated, warning = svc.generate_exam_numbers(db, body.semester_id, body.grade)
    log_exam_action(
        db, user, "exam_number_generate",
        target_type="semester", target_id=body.semester_id,
        detail=f"生成{body.grade}年级考号{generated}人",
    )
    db.commit()
    return ExamNumberGenerateOut(generated=generated, warning=warning)
