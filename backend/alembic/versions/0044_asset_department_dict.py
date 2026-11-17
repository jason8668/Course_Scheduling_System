"""学校资产管理系统一期补半成品 #76:部门字典。

- 新建 asset_departments 表(部门一级字典,组织架构四级 校区/楼栋/部门/
  房间 中的部门一级):id、name 唯一、code 可空唯一、parent_id 自引用
  可空、is_active、created_at。
- 数据迁移:从 asset_cards 的 manage_dept / use_dept 取 distinct 非空
  值建字典行;资产卡加 manage_dept_id / use_dept_id(外键 SET NULL),
  按名字回填。
- 原 manage_dept / use_dept 字符串列保留(兼容与回滚):降级时删外键列
  与字典表即可,字符串口径不受影响。

Revision ID: 0044_asset_department_dict
Revises: 0043_asset_disposal_sync
"""

import sqlalchemy as sa

from alembic import op

revision = "0044_asset_department_dict"
down_revision = "0043_asset_disposal_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "asset_departments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("code", sa.String(32), nullable=True),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], ["asset_departments.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("name", name="uq_asset_departments_name"),
        sa.UniqueConstraint("code", name="uq_asset_departments_code"),
    )
    op.create_index("ix_asset_departments_name", "asset_departments", ["name"])
    op.create_index("ix_asset_departments_parent_id", "asset_departments", ["parent_id"])

    # 已有表加外键列用 batch 模式(#84 的 0045 同款写法):SQLite 不支持
    # ALTER 加约束,Postgres 走普通 ALTER,两边都通。
    with op.batch_alter_table("asset_cards") as batch_op:
        batch_op.add_column(sa.Column("manage_dept_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("use_dept_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_asset_cards_manage_dept_id", "asset_departments",
            ["manage_dept_id"], ["id"], ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_asset_cards_use_dept_id", "asset_departments",
            ["use_dept_id"], ["id"], ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_asset_cards_manage_dept_id", ["manage_dept_id"])
        batch_op.create_index(
            "ix_asset_cards_use_dept_id", ["use_dept_id"])

    _backfill_departments()


def _backfill_departments() -> None:
    """数据迁移:字典行取两列 distinct 非空字符串的并集;外键按名字回填。

    注意 Postgres 写法:
    - 布尔写 true,不写 1(SQLite 把布尔当整数,本地测不出来);
    - 字符串里不写 ASCII 冒号,避免 sa.text() 把冒号后内容当绑定参数。
    """
    conn = op.get_bind()
    conn.execute(sa.text(
        "INSERT INTO asset_departments (name, is_active) "
        "SELECT DISTINCT name, true FROM ("
        "SELECT manage_dept AS name FROM asset_cards "
        "UNION SELECT use_dept AS name FROM asset_cards"
        ") AS dept_names "
        "WHERE name IS NOT NULL AND name <> '' "
        "AND NOT EXISTS (SELECT 1 FROM asset_departments d WHERE d.name = dept_names.name)"
    ))
    conn.execute(sa.text(
        "UPDATE asset_cards SET manage_dept_id = "
        "(SELECT id FROM asset_departments "
        "WHERE asset_departments.name = asset_cards.manage_dept) "
        "WHERE manage_dept IS NOT NULL AND manage_dept <> ''"
    ))
    conn.execute(sa.text(
        "UPDATE asset_cards SET use_dept_id = "
        "(SELECT id FROM asset_departments "
        "WHERE asset_departments.name = asset_cards.use_dept) "
        "WHERE use_dept IS NOT NULL AND use_dept <> ''"
    ))


def downgrade() -> None:
    with op.batch_alter_table("asset_cards") as batch_op:
        batch_op.drop_constraint(
            "fk_asset_cards_use_dept_id", type_="foreignkey")
        batch_op.drop_constraint(
            "fk_asset_cards_manage_dept_id", type_="foreignkey")
        batch_op.drop_index("ix_asset_cards_use_dept_id")
        batch_op.drop_index("ix_asset_cards_manage_dept_id")
        batch_op.drop_column("use_dept_id")
        batch_op.drop_column("manage_dept_id")
    op.drop_table("asset_departments")
