"""M6-3:部分排课的未排清单随草稿持久化。

先前未排清单只活在 Redis(24h TTL):部分排课草稿被 force 发布之后,solver 说「这几门
课排不下、原因是什么」的纪录就消失了。哪些配课还缺节数可由 completeness 从 DB 重算,
但**原因**只有 solver 知道,不存就永远遗失。

Revision ID: 0016_timetable_unscheduled
Revises: 0015_app_settings
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0016_timetable_unscheduled"
down_revision = "0015_app_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "timetables",
        sa.Column(
            "unscheduled",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("timetables", "unscheduled")
