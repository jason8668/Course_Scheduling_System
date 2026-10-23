"""M6-5:同学期班名唯一。

冲突讯息、课表、导出全都以班名指称班级——同学期出现两个「301」时,组长在界面上根本
分不出是哪一班。加约束前必须先处理既有的重复资料,否则有重复班名的学校升级会直接失败
(而他们正是最需要这个约束的人)。重复者依 id 顺序改名为「301 (2)」「301 (3)」…,
不删任何资料,课表与配课全部保留;组长升级后可自行改成正确的班名。

Revision ID: 0017_class_name_unique
Revises: 0016_timetable_unscheduled
"""

import sqlalchemy as sa

from alembic import op

revision = "0017_class_name_unique"
down_revision = "0016_timetable_unscheduled"
branch_labels = None
depends_on = None


def _dedupe_existing_names(conn) -> None:
    rows = conn.execute(
        sa.text(
            """
            SELECT id, semester_id, name FROM class_units c
            WHERE EXISTS (
                SELECT 1 FROM class_units o
                WHERE o.semester_id = c.semester_id AND o.name = c.name AND o.id <> c.id
            )
            ORDER BY semester_id, name, id
            """
        )
    ).all()

    seen: dict[tuple[int, str], int] = {}
    for row_id, semester_id, name in rows:
        key = (semester_id, name)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] == 1:
            continue  # 第一笔保留原名
        # 找一个还没被用掉的名字(理论上 (2) 就够,但不排除学校自己已经有「301 (2)」)
        suffix = seen[key]
        while True:
            candidate = f"{name} ({suffix})"
            taken = conn.execute(
                sa.text(
                    "SELECT 1 FROM class_units "
                    "WHERE semester_id = :sid AND name = :n LIMIT 1"
                ),
                {"sid": semester_id, "n": candidate},
            ).first()
            if not taken:
                break
            suffix += 1
        conn.execute(
            sa.text("UPDATE class_units SET name = :n WHERE id = :i"),
            {"n": candidate, "i": row_id},
        )


def upgrade() -> None:
    _dedupe_existing_names(op.get_bind())
    op.create_unique_constraint(
        "uq_class_units_semester_name", "class_units", ["semester_id", "name"]
    )


def downgrade() -> None:
    # 改过的班名不还原(无法分辨哪些是升级改的、哪些是组长自己取的)
    op.drop_constraint("uq_class_units_semester_name", "class_units", type_="unique")
