"""钉钉群调代课措辞(Jason 2026-10-30 给的模板原样,三类)。

用 special_days 的 _base:王小明教 1 班数学(周一第 1 节已发布)。
直接调 _notify_handler / clear 的通知写入,断言正文就是用户给的句式。
"""

from app.models.leave import AffectedPeriod, AffectedStatus, LeaveRequest, LeaveType
from app.models.notification import Notification
from app.models.substitution import Substitution, SubstitutionType
from app.services import substitutions as sub_svc
from tests.dates import MON
from tests.test_special_days import _base


def _affected(db, ctx):
    leave = LeaveRequest(
        semester_id=ctx["sem"].id, teacher_id=ctx["t1"].id,
        leave_type=LeaveType.sick.value, start_date=MON, end_date=MON,
        status="registered",
    )
    db.add(leave)
    db.flush()
    ap = AffectedPeriod(
        semester_id=ctx["sem"].id, leave_request_id=leave.id, date=MON,
        weekday=MON.isoweekday(),
        period_no=1, period_name="第1节", class_names="七年级1班",
        subject_name="数学", status=AffectedStatus.pending.value,
        course_assignment_id=ctx["a1"].id,
    )
    db.add(ap)
    db.commit()
    return ap


def _notes(db, teacher_id):
    return db.query(Notification).filter_by(teacher_id=teacher_id).order_by(Notification.id).all()


def test_substitute_wording_is_user_template(db):
    ctx = _base(db)
    ap = _affected(db, ctx)
    sub = Substitution(
        semester_id=ctx["sem"].id,
        affected_period_id=ap.id, type=SubstitutionType.substitute.value,
        handler_teacher_id=ctx["t2"].id,
    )
    db.add(sub)
    db.commit()
    sub_svc._notify_handler(db, ap, sub, ctx["t2"])
    db.commit()
    body = _notes(db, ctx["t2"].id)[-1].body
    # 句式与用户模板一致(日期取 fixture 的 MON,故只断句式):“第1节,七年级1班
    # 《数学》,王小明老师调课,由李小红老师代课。”且无第二人称
    assert body == (
        f"{MON.month}月{MON.day}日 第1节,七年级1班《数学》,王小明老师调课,"
        "由李小红老师代课。"
    )
    assert "您" not in body


def test_swap_wording_is_user_template(db):
    ctx = _base(db)
    ap = _affected(db, ctx)
    sub = Substitution(
        semester_id=ctx["sem"].id,
        affected_period_id=ap.id, type=SubstitutionType.swap.value,
        handler_teacher_id=ctx["t2"].id,
        swap_date=MON, swap_period_name="第2节",
        swap_class_names="七年级2班", swap_subject_name="语文",
    )
    db.add(sub)
    db.commit()
    sub_svc._notify_handler(db, ap, sub, ctx["t2"])
    db.commit()
    bodies = [n.body for n in _notes(db, ctx["t2"].id)]
    assert any("王小明老师与李小红老师对调" in b for b in bodies)
    assert any("李小红老师代王小明老师上这节" in b for b in bodies)
    assert any("补李小红老师七年级2班的《语文》" in b for b in bodies)
    assert all("您" not in b for b in bodies)
