"""v1.3.0:单双周课程。

配课多一栏 `week_parity`:空 = 每周都上(既有的所有配课都是这个值,行为完全不变);
odd/even = 只在单周/双周上。单双周的两笔配课放在同一个「单双周组」
(scheduling_units.unit_type = 'alternate',沿用既有栏位,不需改表)。

只新增一个可为空的栏位,不改既有资料:从任何 v1.2.x 升上来,所有课表、请假、
代课纪录都照旧。

Revision ID: 0018_alternate_weeks
Revises: 0017_class_name_unique
"""

import sqlalchemy as sa

from alembic import op

revision = "0018_alternate_weeks"
down_revision = "0017_class_name_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "course_assignments",
        sa.Column("week_parity", sa.String(length=4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("course_assignments", "week_parity")
