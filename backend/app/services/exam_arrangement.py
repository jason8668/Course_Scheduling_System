"""考场编排服务(KW-15~22):考场设置、编排规则、自动编排、手动调整、座位表、导出、锁定。

权限口径:写操作只允许 admin/director(由 API 层 require_roles +
can_manage_students 把关);读操作按 exam_scopes 的可见范围过滤,
教师只看本人可见班级的编排。

编排口径(KW-16 清单原文,三选一,全年级统一执行):
- whole_class 模式:按班级顺序整班填满考场(先按班级、再按学号排,
  依次填满每间考场);scatter_same_class 在此模式下不起作用。
- s_shape 模式:有上一次同类型考试成绩时,按总分降序蛇形编排;
  没有可比的上次考试时返回警告全文并暂按学号顺序编排,绝不假装按成绩排过。
- random 模式:确定性随机混排,种子 seed = exam_id * 1000 + subject_id,
  同一科目重复编排结果一致。
- 每考场人数上限 = min(考场有效容量, 规则 max_per_room);考场容量
  为空时取教室 capacity,教室 capacity 也为空时只受 max_per_room 限制。
- 只编排状态为正常的参试学生;缺考/免考不进考场,计入 warnings。
- 单独考场类型的特殊考生优先分到 is_special 的考场;没有特殊考场
  可用时给警告,不静默忽略;延长时限、放大字号在座位表里备注。
- 容量不足时编排已排得进的人,剩余人数写进 warnings 预警,不整体失败。
"""

import random
from io import BytesIO

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.basedata import ClassUnit, Room, Subject
from app.models.exam import Exam, ExamParticipant, ExamSpecialArrangement, ExamSubject
from app.models.exam_scores import ExamScore
from app.models.exam_arrangement import (
    DEFAULT_ARRANGEMENT_MODE,
    DEFAULT_MAX_PER_ROOM,
    DEFAULT_SCATTER_SAME_CLASS,
    S_SHAPE_NO_SCORE_WARNING,
    ExamArrangementLock,
    ExamArrangementRule,
    ExamRoom,
    ExamRoomAssignment,
)
from app.models.exam_foundation import Student
from app.models.user import User
from app.services.exam import get_exam, require_exam_not_archived, require_exam_visible
from app.services.exam_scopes import visible_class_ids

ARRANGEMENT_MODES = ("whole_class", "s_shape", "random")
EXAM_ROOM_TYPES = ("普通", "特殊")


# ── 共用 ──────────────────────────────
def _room_name_map(db: Session, room_ids: set[int]) -> dict[int, str]:
    if not room_ids:
        return {}
    return {
        r.id: r.name
        for r in db.scalars(select(Room).where(Room.id.in_(room_ids))).all()
    }


def _require_exam_room(db: Session, exam_id: int, room_id: int) -> ExamRoom:
    row = db.scalar(
        select(ExamRoom).where(
            ExamRoom.exam_id == exam_id, ExamRoom.room_id == room_id
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到考场")
    return row


def _get_lock(db: Session, exam_id: int) -> ExamArrangementLock | None:
    return db.scalar(
        select(ExamArrangementLock).where(ExamArrangementLock.exam_id == exam_id)
    )


def is_locked(db: Session, exam_id: int) -> bool:
    return _get_lock(db, exam_id) is not None


def _require_not_locked(db: Session, exam_id: int) -> None:
    if is_locked(db, exam_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "编排已锁定,请先解锁再调整")


def _room_limit(db: Session, exam_room: ExamRoom, rule: ExamArrangementRule) -> int:
    """某考场本场可排人数上限。"""
    cap = exam_room.capacity
    if cap is None:
        room = db.get(Room, exam_room.room_id)
        cap = room.capacity if room is not None else None
    if cap is None:
        return rule.max_per_room
    return min(cap, rule.max_per_room)


def _special_notes(db: Session, exam_id: int) -> dict[int, str]:
    """学生 id -> 特殊安排备注(类型 + 详情,用分号连接)。"""
    rows = db.scalars(
        select(ExamSpecialArrangement)
        .where(ExamSpecialArrangement.exam_id == exam_id)
        .order_by(ExamSpecialArrangement.id)
    ).all()
    notes: dict[int, list[str]] = {}
    for r in rows:
        text = r.arrangement_type
        if r.detail:
            text = f"{text}({r.detail})"
        notes.setdefault(r.student_id, []).append(text)
    return {sid: "；".join(v) for sid, v in notes.items()}


def _participant_class_ids(db: Session, exam_id: int) -> dict[int, int]:
    """学生 id -> 参试名单快照班级 id。"""
    rows = db.execute(
        select(ExamParticipant.student_id, ExamParticipant.class_unit_id).where(
            ExamParticipant.exam_id == exam_id
        )
    ).all()
    return {sid: cid for sid, cid in rows}


def _assignment_out(
    db: Session,
    row: ExamRoomAssignment,
    subject_names: dict[int, str],
    room_names: dict[int, str],
    students: dict[int, Student],
    class_names: dict[int, str],
    class_grades: dict[int, int],
    participant_classes: dict[int, int],
    special_notes: dict[int, str],
) -> dict:
    student = students.get(row.student_id)
    class_id = participant_classes.get(row.student_id)
    return {
        "id": row.id,
        "exam_id": row.exam_id,
        "subject_id": row.subject_id,
        "subject_name": subject_names.get(row.subject_id, ""),
        "room_id": row.room_id,
        "room_name": room_names.get(row.room_id, ""),
        "student_id": row.student_id,
        "student_no": student.student_no if student else "",
        "exam_no": student.exam_no if student and student.exam_no else "",
        "student_name": student.name if student else "",
        "class_name": class_names.get(class_id, "") if class_id else "",
        "grade": class_grades.get(class_id) if class_id else None,
        "seat_no": row.seat_no,
        "special_note": special_notes.get(row.student_id, ""),
    }


def _visible_assignments(
    db: Session, user: User, exam_id: int,
    subject_id: int | None = None, room_id: int | None = None,
) -> list[ExamRoomAssignment]:
    """按可见范围过滤后的编排结果(教师只看本人可见班级)。"""
    stmt = select(ExamRoomAssignment).where(
        ExamRoomAssignment.exam_id == exam_id
    )
    if subject_id is not None:
        stmt = stmt.where(ExamRoomAssignment.subject_id == subject_id)
    if room_id is not None:
        stmt = stmt.where(ExamRoomAssignment.room_id == room_id)
    rows = db.scalars(stmt.order_by(
        ExamRoomAssignment.room_id, ExamRoomAssignment.seat_no
    )).all()
    class_ids = visible_class_ids(db, user)
    if class_ids is None:
        return list(rows)
    participant_classes = _participant_class_ids(db, exam_id)
    return [
        r for r in rows
        if participant_classes.get(r.student_id) in class_ids
    ]


# ── 考场设置(KW-15) ──────────────────────────────
def list_rooms(db: Session, exam: Exam) -> tuple[list[dict], int]:
    rows = db.scalars(
        select(ExamRoom).where(ExamRoom.exam_id == exam.id)
        .order_by(ExamRoom.id)
    ).all()
    names = _room_name_map(db, {r.room_id for r in rows})
    items = [
        {
            "id": r.id,
            "exam_id": r.exam_id,
            "room_id": r.room_id,
            "room_name": names.get(r.room_id, ""),
            "capacity": r.capacity,
            "room_type": r.room_type,
            "is_special": r.is_special,
        }
        for r in rows
    ]
    return items, len(items)


def create_room(
    db: Session, exam: Exam, room_id: int, capacity: int | None,
    room_type: str, is_special: bool,
) -> ExamRoom:
    require_exam_not_archived(db, exam.id)
    room = db.get(Room, room_id)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到教室")
    if room.semester_id != exam.semester_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "教室不属于本考试学期")
    if room_type not in EXAM_ROOM_TYPES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "考场类型只能是普通或特殊"
        )
    dup = db.scalar(
        select(ExamRoom.id).where(
            ExamRoom.exam_id == exam.id, ExamRoom.room_id == room_id
        )
    )
    if dup is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "该教室已设为考场")
    row = ExamRoom(
        exam_id=exam.id, room_id=room_id, capacity=capacity,
        room_type=room_type, is_special=is_special,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def create_rooms_bulk(
    db: Session, exam: Exam, room_ids: list[int], capacity: int | None,
    room_type: str, is_special: bool,
) -> tuple[int, int]:
    """批量添加考场:一次勾选多间教室;已设为考场/不存在/不属于本学期者计入跳过,不中断整批。
    人数上限不填时每间用各自教室的容量,填了则对所选全部生效;一次提交。"""
    require_exam_not_archived(db, exam.id)
    if room_type not in EXAM_ROOM_TYPES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "考场类型只能是普通或特殊"
        )
    created = 0
    skipped = 0
    for room_id in dict.fromkeys(room_ids):
        room = db.get(Room, room_id)
        if room is None or room.semester_id != exam.semester_id:
            skipped += 1
            continue
        dup = db.scalar(
            select(ExamRoom.id).where(
                ExamRoom.exam_id == exam.id, ExamRoom.room_id == room_id
            )
        )
        if dup is not None:
            skipped += 1
            continue
        db.add(ExamRoom(
            exam_id=exam.id, room_id=room_id,
            capacity=capacity if capacity is not None else room.capacity,
            room_type=room_type, is_special=is_special,
        ))
        created += 1
    db.commit()
    return created, skipped


def delete_room(db: Session, exam: Exam, rid: int) -> None:
    require_exam_not_archived(db, exam.id)
    row = db.get(ExamRoom, rid)
    if row is None or row.exam_id != exam.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到考场")
    used = db.scalar(
        select(func.count()).select_from(ExamRoomAssignment).where(
            ExamRoomAssignment.exam_id == exam.id,
            ExamRoomAssignment.room_id == row.room_id,
        )
    ) or 0
    if used:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "该考场已有编排结果,请先清空编排再删除"
        )
    db.delete(row)
    db.commit()


# ── 编排规则(KW-16) ──────────────────────────────
def get_rule(db: Session, exam: Exam) -> ExamArrangementRule:
    row = db.scalar(
        select(ExamArrangementRule).where(
            ExamArrangementRule.exam_id == exam.id
        )
    )
    if row is not None:
        return row
    return ExamArrangementRule(
        exam_id=exam.id,
        mode=DEFAULT_ARRANGEMENT_MODE,
        scatter_same_class=DEFAULT_SCATTER_SAME_CLASS,
        max_per_room=DEFAULT_MAX_PER_ROOM,
    )


def upsert_rule(
    db: Session, exam: Exam, mode: str, scatter_same_class: bool, max_per_room: int
) -> ExamArrangementRule:
    require_exam_not_archived(db, exam.id)
    if mode not in ARRANGEMENT_MODES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "编排方式只能是按班级整班、按成绩 S 型混排或随机混排",
        )
    if max_per_room < 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "每考场人数上限至少为 1")
    row = db.scalar(
        select(ExamArrangementRule).where(
            ExamArrangementRule.exam_id == exam.id
        )
    )
    if row is None:
        row = ExamArrangementRule(exam_id=exam.id)
        db.add(row)
    row.mode = mode
    row.scatter_same_class = scatter_same_class
    row.max_per_room = max_per_room
    db.commit()
    db.refresh(row)
    return row


# ── 自动编排(KW-17) ──────────────────────────────
def _round_robin(groups: list[list[dict]]) -> list[dict]:
    """按班级轮流取人,打散同班相邻座位。"""
    out: list[dict] = []
    idx = 0
    remaining = True
    while remaining:
        remaining = False
        for g in groups:
            if idx < len(g):
                out.append(g[idx])
                remaining = True
        idx += 1
    return out


def _order_students(
    items: list[dict], mode: str, scatter: bool, seed: int | None = None
) -> list[dict]:
    """items:每项含 student_no、class_unit_id。返回排好序的新列表。

    whole_class:按班级顺序整班填满考场(先按班级、再按学号),
      scatter 在此模式下不起作用。
    random:确定性随机混排,种子由调用方按 exam_id * 1000 + subject_id 给出,
      同一科目重复编排结果一致。
    s_shape:无成绩时暂按学号顺序编(由调用方先查上次成绩;
      有成绩时调用方用 _snake_fill_order 排,不走这里),
      scatter 为真时按班级轮流取人打散同班相邻座位。
    """
    by_no = sorted(items, key=lambda x: (x["student_no"], x["student_id"]))
    if mode == "whole_class":
        return sorted(
            items,
            key=lambda x: (x["class_unit_id"], x["student_no"], x["student_id"]),
        )
    if mode == "random":
        shuffled = list(by_no)
        random.Random(seed).shuffle(shuffled)
        return shuffled
    if not scatter:
        return by_no
    groups_map: dict[int, list[dict]] = {}
    for it in by_no:
        groups_map.setdefault(it["class_unit_id"], []).append(it)
    groups = sorted(groups_map.values(), key=lambda g: g[0]["student_no"])
    return _round_robin(groups)


def _previous_exam_total_scores(db: Session, exam: Exam) -> dict[int, float] | None:
    """上一次同类型考试的总分表(学生 id -> 各科成绩之和)。

    上一次 = 同学期、同 exam_type、状态已到"已发布成绩"或之后(已发布成绩/已归档)、
    创建时间早于本次考试;取其中最近的一次。没有这样的考试,或该考试
    没有任何成绩数据时回传 None,调用方保持原有行为(警告 + 按学号编)。
    """
    prev = db.scalar(
        select(Exam).where(
            Exam.semester_id == exam.semester_id,
            Exam.exam_type == exam.exam_type,
            Exam.id != exam.id,
            Exam.status.in_(("已发布成绩", "已归档")),
            (Exam.created_at < exam.created_at)
            | ((Exam.created_at == exam.created_at) & (Exam.id < exam.id)),
        ).order_by(Exam.created_at.desc(), Exam.id.desc())
    )
    if prev is None:
        return None
    rows = db.execute(
        select(ExamScore.student_id, func.sum(ExamScore.score)).where(
            ExamScore.exam_id == prev.id,
            ExamScore.score.is_not(None),
        ).group_by(ExamScore.student_id)
    ).all()
    totals = {sid: float(total) for sid, total in rows if total is not None}
    return totals or None


def _snake_fill_order(
    items: list[dict], totals: dict[int, float],
    room_limits: list[tuple[int, int]],
) -> list[dict]:
    """按总分蛇形编排后的填考场顺序。

    先按总分降序排(无成绩的学生排最后,同分按学号),再按蛇形发牌:
    正向每间考场发一人,反向每间考场发一人,交替进行,直到发完;
    最后按考场顺序摊平,使顺序填考场时每间考场拿到的正是蛇形分到的人。
    容量不足发不完的学生缀在末尾,由调用方按容量不足处理。
    """
    ranked = sorted(
        items,
        key=lambda x: (
            0 if x["student_id"] in totals else 1,
            -totals.get(x["student_id"], 0.0),
            x["student_no"],
            x["student_id"],
        ),
    )
    dealt: dict[int, list[dict]] = {rid: [] for rid, _ in room_limits}
    remaining = dict(room_limits)
    order = [rid for rid, _ in room_limits]
    idx = 0
    forward = True
    while idx < len(ranked):
        seq = order if forward else list(reversed(order))
        progressed = False
        for rid in seq:
            if idx >= len(ranked):
                break
            if remaining.get(rid, 0) <= 0:
                continue
            dealt[rid].append(ranked[idx])
            remaining[rid] -= 1
            idx += 1
            progressed = True
        if not progressed:
            break
        forward = not forward
    out: list[dict] = []
    for rid, _ in room_limits:
        out.extend(dealt[rid])
    out.extend(ranked[idx:])
    return out


def arrange(
    db: Session, exam: Exam, subject_id: int | None
) -> tuple[dict, int]:
    require_exam_not_archived(db, exam.id)
    """自动编排;返回 (结果字典, 本次清空的旧编排条数)。

    指定 subject_id 只编该科,不指定则编全部已设科目。
    """
    _require_not_locked(db, exam.id)
    rooms = db.scalars(
        select(ExamRoom).where(ExamRoom.exam_id == exam.id)
        .order_by(ExamRoom.id)
    ).all()
    if not rooms:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "请先设置考场再编排")
    if subject_id is not None:
        subj = db.scalar(
            select(ExamSubject).where(
                ExamSubject.exam_id == exam.id,
                ExamSubject.subject_id == subject_id,
            )
        )
        if subj is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到该考试科目")
        subjects = [subject_id]
    else:
        subjects = [
            r.subject_id
            for r in db.scalars(
                select(ExamSubject).where(ExamSubject.exam_id == exam.id)
                .order_by(ExamSubject.exam_date, ExamSubject.start_time)
            ).all()
        ]
    if not subjects:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "考试尚未设置科目,请先设置科目再编排")
    participants = db.scalars(
        select(ExamParticipant).where(ExamParticipant.exam_id == exam.id)
        .order_by(ExamParticipant.id)
    ).all()
    if not participants:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "参试名单为空,请先生成参试名单再编排")
    rule = get_rule(db, exam)
    warnings: list[str] = []
    # S 型:有上一次同类型考试成绩时真按成绩排,不写警告;
    # 没有可比的上次考试时警告全文 + 暂按学号顺序编(原有行为)。
    s_totals: dict[int, float] | None = None
    if rule.mode == "s_shape":
        s_totals = _previous_exam_total_scores(db, exam)
        if s_totals is None:
            warnings.append(S_SHAPE_NO_SCORE_WARNING)
    excluded = sum(1 for p in participants if p.status != "正常")
    if excluded:
        warnings.append(f"缺考或免考学生{excluded}人不参与编排")
    normal = [p for p in participants if p.status == "正常"]
    student_ids = [p.student_id for p in normal]
    students = {
        s.id: s
        for s in db.scalars(select(Student).where(Student.id.in_(student_ids))).all()
    } if student_ids else {}
    items = [
        {
            "student_id": p.student_id,
            "class_unit_id": p.class_unit_id,
            "student_no": students[p.student_id].student_no
            if p.student_id in students else "",
        }
        for p in normal
    ]
    special_rows = db.scalars(
        select(ExamSpecialArrangement).where(
            ExamSpecialArrangement.exam_id == exam.id
        )
    ).all()
    solo_ids = {
        r.student_id for r in special_rows if r.arrangement_type == "单独考场"
    }
    special_rooms = [r for r in rooms if r.is_special or r.room_type == "特殊"]
    normal_rooms = [r for r in rooms if r not in special_rooms]
    if solo_ids and not special_rooms:
        warnings.append("没有特殊考场可用，单独考场考生已按普通考场编排")
    # 重新编排先清空该科已编排结果。
    cleared = db.query(ExamRoomAssignment).filter(
        ExamRoomAssignment.exam_id == exam.id,
        ExamRoomAssignment.subject_id.in_(subjects),
    ).delete(synchronize_session=False)
    db.flush()
    assigned = 0
    rooms_used: set[int] = set()
    unassigned = 0
    for subject in subjects:
        # 随机混排的种子与科目有关,每科单独算顺序,保证同一科目重复编排结果一致。
        # S 型有成绩时:按总分蛇形排,考场顺序与普通考生分房偏好一致(普通考场在前)。
        if rule.mode == "s_shape" and s_totals is not None:
            room_order = normal_rooms + special_rooms
            limits = [(r.room_id, _room_limit(db, r, rule)) for r in room_order]
            ordered = _snake_fill_order(items, s_totals, limits)
        else:
            ordered = _order_students(
                items, rule.mode, rule.scatter_same_class,
                seed=exam.id * 1000 + subject,
            )
        remaining: dict[int, int] = {
            r.room_id: _room_limit(db, r, rule) for r in rooms
        }
        next_seat: dict[int, int] = {r.room_id: 1 for r in rooms}

        def _alloc(student_id: int, preferred: list[ExamRoom]) -> bool:
            for r in preferred:
                if remaining.get(r.room_id, 0) > 0:
                    db.add(ExamRoomAssignment(
                        exam_id=exam.id, subject_id=subject,
                        room_id=r.room_id, student_id=student_id,
                        seat_no=next_seat[r.room_id],
                    ))
                    remaining[r.room_id] -= 1
                    next_seat[r.room_id] += 1
                    rooms_used.add(r.room_id)
                    return True
            return False

        for it in ordered:
            sid = it["student_id"]
            if sid in solo_ids:
                ok = _alloc(sid, special_rooms + normal_rooms)
            else:
                ok = _alloc(sid, normal_rooms + special_rooms)
            if ok:
                assigned += 1
            else:
                unassigned += 1
    if unassigned:
        warnings.append(f"考场容量不足，仅编排{assigned}人，{unassigned}人未编排")
    # 已编排的特殊考生标记为已安排。
    if assigned:
        db.flush()  # 先落库,否则下面查询在 autoflush=False 的会话里看不到新编排
        assigned_ids = {
            sid for (sid,) in db.execute(
                select(ExamRoomAssignment.student_id).where(
                    ExamRoomAssignment.exam_id == exam.id,
                    ExamRoomAssignment.subject_id.in_(subjects),
                )
            ).all()
        }
        for r in special_rows:
            if r.student_id in assigned_ids and r.status != "已安排":
                r.status = "已安排"
    db.commit()
    return (
        {"assigned": assigned, "rooms_used": len(rooms_used), "warnings": warnings},
        cleared,
    )


# ── 编排结果查询(KW-19) ──────────────────────────────
def assignment_to_out(db: Session, row: ExamRoomAssignment) -> dict:
    """单条编排记录转出参字典(供 move/swap 接口复用)。"""
    subject_names = _subject_name_map(db, {row.subject_id})
    room_names = _room_name_map(db, {row.room_id})
    students = {
        s.id: s
        for s in db.scalars(
            select(Student).where(Student.id == row.student_id)
        ).all()
    }
    _all_classes = db.scalars(select(ClassUnit)).all()
    class_names = {c.id: c.name for c in _all_classes}
    class_grades = {c.id: c.grade for c in _all_classes}
    return _assignment_out(
        db, row, subject_names, room_names, students, class_names,
        class_grades,
        _participant_class_ids(db, row.exam_id),
        _special_notes(db, row.exam_id),
    )


def _subject_name_map(db: Session, subject_ids: set[int]) -> dict[int, str]:
    if not subject_ids:
        return {}
    return {
        s.id: s.name
        for s in db.scalars(
            select(Subject).where(Subject.id.in_(subject_ids))
        ).all()
    }


def list_assignments(
    db: Session, user: User, exam: Exam,
    subject_id: int | None = None, room_id: int | None = None,
) -> tuple[list[dict], int]:
    require_exam_visible(db, user, exam)
    rows = _visible_assignments(db, user, exam.id, subject_id, room_id)
    subject_names = {
        s.id: s.name
        for s in db.scalars(
            select(Subject).where(
                Subject.id.in_({r.subject_id for r in rows})
            )
        ).all()
    } if rows else {}
    room_names = _room_name_map(db, {r.room_id for r in rows})
    students = {
        s.id: s
        for s in db.scalars(
            select(Student).where(
                Student.id.in_({r.student_id for r in rows})
            )
        ).all()
    } if rows else {}
    _all_classes = db.scalars(select(ClassUnit)).all()
    class_names = {c.id: c.name for c in _all_classes}
    class_grades = {c.id: c.grade for c in _all_classes}
    participant_classes = _participant_class_ids(db, exam.id)
    special_notes = _special_notes(db, exam.id)
    items = [
        _assignment_out(
            db, r, subject_names, room_names, students, class_names,
            class_grades,
            participant_classes, special_notes,
        )
        for r in rows
    ]
    return items, len(items)


def seat_map(
    db: Session, user: User, exam: Exam, subject_id: int | None = None
) -> dict:
    """座位表(KW-19):按考场出座位清单;不指定科目时返回全部科目的编排。

    不指定科目时同一考场可能出现多科座位,座位按科目名、座位号排序,
    建议前端按科目查座位表。
    """
    require_exam_visible(db, user, exam)
    rows = _visible_assignments(db, user, exam.id, subject_id, None)
    room_names = _room_name_map(db, {r.room_id for r in rows})
    students = {
        s.id: s
        for s in db.scalars(
            select(Student).where(
                Student.id.in_({r.student_id for r in rows})
            )
        ).all()
    } if rows else {}
    _all_classes = db.scalars(select(ClassUnit)).all()
    class_names = {c.id: c.name for c in _all_classes}
    class_grades = {c.id: c.grade for c in _all_classes}
    participant_classes = _participant_class_ids(db, exam.id)
    special_notes = _special_notes(db, exam.id)
    subject_names = {
        s.id: s.name
        for s in db.scalars(
            select(Subject).where(
                Subject.id.in_({r.subject_id for r in rows})
            )
        ).all()
    } if rows else {}
    grouped: dict[int, list[dict]] = {}
    for r in rows:
        grouped.setdefault(r.room_id, []).append(r)
    rooms_out = []
    for room_id in sorted(grouped, key=lambda rid: room_names.get(rid, "")):
        entries = sorted(
            grouped[room_id],
            key=lambda r: (subject_names.get(r.subject_id, ""), r.seat_no),
        )
        seats = []
        for r in entries:
            student = students.get(r.student_id)
            class_id = participant_classes.get(r.student_id)
            seats.append({
                "seat_no": r.seat_no,
                "student_no": student.student_no if student else "",
                "exam_no": student.exam_no if student and student.exam_no else "",
                "student_name": student.name if student else "",
                "class_name": class_names.get(class_id, "") if class_id else "",
                "grade": class_grades.get(class_id) if class_id else None,
                "special_note": special_notes.get(r.student_id, ""),
            })
        rooms_out.append({
            "room_id": room_id,
            "room_name": room_names.get(room_id, ""),
            "seats": seats,
        })
    return {"rooms": rooms_out}


# ── 准考证数据(KW-19) ──────────────────────────────
def list_admission_tickets(
    db: Session, user: User, exam: Exam,
    class_unit_id: int | None = None, room_id: int | None = None,
) -> tuple[list[dict], int]:
    """准考证数据:每名正常参试学生一条,附全部科目日程与考场座位。

    只含状态为正常的参试学生(缺考/免考不进考场,不发准考证)。
    class_unit_id 按参试名单快照班级筛选,供按班级分发打印;
    room_id 只保留在该考场至少有一科编排的考生。
    某科未编排时该科 room_name 为空、seat_no 为空。
    照片不做:无照片数据源(清单 KW-19 备注)。
    """
    require_exam_visible(db, user, exam)
    participants = db.scalars(
        select(ExamParticipant).where(
            ExamParticipant.exam_id == exam.id,
            ExamParticipant.status == "正常",
        )
    ).all()
    class_ids = visible_class_ids(db, user)
    if class_ids is not None:
        participants = [
            p for p in participants if p.class_unit_id in class_ids
        ]
    if class_unit_id is not None:
        participants = [
            p for p in participants if p.class_unit_id == class_unit_id
        ]
    subjects = db.scalars(
        select(ExamSubject).where(ExamSubject.exam_id == exam.id)
        .order_by(ExamSubject.exam_date, ExamSubject.start_time)
    ).all()
    assignments = db.scalars(
        select(ExamRoomAssignment).where(
            ExamRoomAssignment.exam_id == exam.id
        )
    ).all()
    seat_by_key: dict[tuple[int, int], tuple[int, int]] = {
        (a.subject_id, a.student_id): (a.room_id, a.seat_no)
        for a in assignments
    }
    room_names = _room_name_map(db, {a.room_id for a in assignments})
    if room_id is not None:
        in_room = {a.student_id for a in assignments if a.room_id == room_id}
        participants = [p for p in participants if p.student_id in in_room]
    subject_names = _subject_name_map(db, {s.subject_id for s in subjects})
    students = {
        s.id: s
        for s in db.scalars(
            select(Student).where(
                Student.id.in_({p.student_id for p in participants})
            )
        ).all()
    } if participants else {}
    _all_classes = db.scalars(select(ClassUnit)).all()
    class_names = {c.id: c.name for c in _all_classes}
    class_grades = {c.id: c.grade for c in _all_classes}
    items = []
    ordered = sorted(
        participants,
        key=lambda p: (
            p.class_unit_id,
            students[p.student_id].student_no
            if p.student_id in students else "",
            p.student_id,
        ),
    )
    for p in ordered:
        student = students.get(p.student_id)
        sub_items = []
        for s in subjects:
            seat = seat_by_key.get((s.subject_id, p.student_id))
            sub_items.append({
                "subject_id": s.subject_id,
                "subject_name": subject_names.get(s.subject_id, ""),
                "exam_date": s.exam_date.isoformat(),
                "start_time": s.start_time.strftime("%H:%M"),
                "end_time": s.end_time.strftime("%H:%M"),
                "room_name": room_names.get(seat[0], "") if seat else "",
                "seat_no": seat[1] if seat else None,
            })
        items.append({
            "student_id": p.student_id,
            "student_no": student.student_no if student else "",
            "exam_no": student.exam_no if student and student.exam_no else "",
            "student_name": student.name if student else "",
            "class_name": class_names.get(p.class_unit_id, ""),
            "grade": class_grades.get(p.class_unit_id),
            "subjects": sub_items,
        })
    return items, len(items)


# ── 手动调整(KW-18) ──────────────────────────────
def move_assignment(
    db: Session, exam: Exam, assignment_id: int,
    to_room_id: int, seat_no: int | None,
) -> ExamRoomAssignment:
    require_exam_not_archived(db, exam.id)
    _require_not_locked(db, exam.id)
    row = db.get(ExamRoomAssignment, assignment_id)
    if row is None or row.exam_id != exam.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到编排记录")
    target = _require_exam_room(db, exam.id, to_room_id)
    rule = get_rule(db, exam)
    limit = _room_limit(db, target, rule)
    peers = db.scalars(
        select(ExamRoomAssignment).where(
            ExamRoomAssignment.exam_id == exam.id,
            ExamRoomAssignment.subject_id == row.subject_id,
            ExamRoomAssignment.room_id == to_room_id,
        )
    ).all()
    same_room = to_room_id == row.room_id
    if not same_room and len(peers) >= limit:
        raise HTTPException(status.HTTP_409_CONFLICT, "目标考场已满员")
    if seat_no is not None:
        clash = next(
            (p for p in peers if p.seat_no == seat_no and p.id != row.id), None
        )
        if clash is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "目标座位已被占用")
        row.seat_no = seat_no
    elif not same_room:
        row.seat_no = (max((p.seat_no for p in peers), default=0) + 1)
    row.room_id = to_room_id
    db.commit()
    db.refresh(row)
    return row


def swap_assignments(
    db: Session, exam: Exam, assignment_id_a: int, assignment_id_b: int
) -> tuple[ExamRoomAssignment, ExamRoomAssignment]:
    require_exam_not_archived(db, exam.id)
    _require_not_locked(db, exam.id)
    a = db.get(ExamRoomAssignment, assignment_id_a)
    b = db.get(ExamRoomAssignment, assignment_id_b)
    if (
        a is None or b is None
        or a.exam_id != exam.id or b.exam_id != exam.id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到编排记录")
    if a.subject_id != b.subject_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "互换座位的两名考生须为同一科目"
        )
    if a.id == b.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能与自己互换座位")
    # 先用临时座位号避开 (考场, 座位号) 唯一约束,再互换考场与座位号。
    a_room, a_seat = a.room_id, a.seat_no
    b_room, b_seat = b.room_id, b.seat_no
    a.seat_no = -1
    db.flush()
    b.room_id, b.seat_no = a_room, a_seat
    db.flush()
    a.room_id, a.seat_no = b_room, b_seat
    db.commit()
    db.refresh(a)
    db.refresh(b)
    return a, b


# ── 导出(KW-20) ──────────────────────────────
def build_arrangement_workbook(
    db: Session, user: User, exam: Exam, subject_id: int | None
) -> bytes:
    """考场安排表 Excel:全科分表,指定科目时只出该科一表。

    每表列:考场、座位号、学号、姓名、班级、备注。
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, Side

    require_exam_visible(db, user, exam)
    if subject_id is not None:
        subj = db.scalar(
            select(ExamSubject).where(
                ExamSubject.exam_id == exam.id,
                ExamSubject.subject_id == subject_id,
            )
        )
        if subj is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到该考试科目")
        subjects = [subject_id]
    else:
        subjects = [
            r.subject_id
            for r in db.scalars(
                select(ExamSubject).where(ExamSubject.exam_id == exam.id)
                .order_by(ExamSubject.exam_date, ExamSubject.start_time)
            ).all()
        ]
    items_by_subject: dict[int, list[dict]] = {}
    for sid in subjects:
        items, _ = list_assignments(db, user, exam, subject_id=sid)
        items_by_subject[sid] = sorted(
            items, key=lambda x: (x["room_name"], x["seat_no"])
        )
    subject_names = {
        s.id: s.name
        for s in db.scalars(
            select(Subject).where(Subject.id.in_(set(subjects)))
        ).all()
    } if subjects else {}
    wb = Workbook()
    thin = Side(style="thin", color="999999")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    header_font = Font(bold=True)
    first = True
    for sid in subjects:
        title = (subject_names.get(sid, "") or "考场安排")[:31] or "考场安排"
        ws = wb.active if first else wb.create_sheet(title)
        if first:
            ws.title = title
            first = False
        ws.append(["考场", "座位号", "学号", "姓名", "班级", "备注"])
        for cell in ws[1]:
            cell.font = header_font
            cell.border = border
            cell.alignment = Alignment(horizontal="center")
        for it in items_by_subject[sid]:
            ws.append([
                it["room_name"], it["seat_no"], it["student_no"],
                it["student_name"], it["class_name"], it["special_note"],
            ])
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.border = border
        widths = [16, 10, 14, 12, 12, 24]
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
    if not subjects:
        ws = wb.active
        ws.title = "考场安排"
        ws.append(["考场", "座位号", "学号", "姓名", "班级", "备注"])
        for cell in ws[1]:
            cell.font = header_font
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_filename(db: Session, exam: Exam, subject_id: int | None) -> str:
    name = exam.name
    if subject_id is not None:
        subj_name = db.scalar(
            select(Subject.name).where(Subject.id == subject_id)
        )
        if subj_name:
            name = f"{name}_{subj_name}"
    return f"{name}考场安排表"


# ── 锁定(KW-22) ──────────────────────────────
def get_lock_info(db: Session, exam: Exam) -> dict:
    row = _get_lock(db, exam.id)
    if row is None:
        return {"locked": False, "locked_by": None, "locked_at": None}
    user = db.get(User, row.locked_by) if row.locked_by else None
    return {
        "locked": True,
        "locked_by": user.username if user else None,
        "locked_at": row.locked_at.isoformat() if row.locked_at else None,
    }


def lock_arrangement(
    db: Session, user: User, exam: Exam, note: str | None
) -> ExamArrangementLock:
    require_exam_not_archived(db, exam.id)
    if _get_lock(db, exam.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "编排已锁定")
    row = ExamArrangementLock(
        exam_id=exam.id, locked_by=user.id, note=note
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def unlock_arrangement(db: Session, exam: Exam) -> None:
    require_exam_not_archived(db, exam.id)
    row = _get_lock(db, exam.id)
    if row is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "编排未锁定")
    db.delete(row)
    db.commit()
