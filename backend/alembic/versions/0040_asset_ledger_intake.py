"""学校资产管理系统一期第 2 批(台账 + 入库验收 + 标签 + 手动勾选核心)。

新建验收单、附件索引、批次号池、勾选记录表;asset_cards 加入库批次、
验收单、入账标志、最近使用时间、闲置标记列;种子参数补闲置识别阈值。
不改已有迁移与已有表语义;不写任何真实官方接口调用;不含学校真实数据。

Revision ID: 0040_asset_ledger_intake
Revises: 0039_asset_foundation
"""

import sqlalchemy as sa

from alembic import op

revision = "0040_asset_ledger_intake"
down_revision = "0039_asset_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "asset_acceptances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("acceptance_no", sa.String(32), nullable=False),
        sa.Column("intake_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), server_default="待验收", nullable=False),
        sa.Column("source_doc", sa.JSON(), nullable=True),
        sa.Column("acceptors", sa.JSON(), nullable=True),
        sa.Column("accepted_by", sa.Integer(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comment", sa.String(500), server_default="", nullable=False),
        sa.Column("batch_no", sa.String(32), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["accepted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("acceptance_no", name="uq_asset_acceptance_no"),
    )
    op.create_index("ix_asset_acceptances_acceptance_no", "asset_acceptances", ["acceptance_no"])
    op.create_index("ix_asset_acceptances_intake_type", "asset_acceptances", ["intake_type"])
    op.create_index("ix_asset_acceptances_batch_no", "asset_acceptances", ["batch_no"])

    op.create_table(
        "asset_attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("file_type", sa.String(16), server_default="其他", nullable=False),
        sa.Column("file_name", sa.String(256), nullable=False),
        sa.Column("file_path", sa.String(512), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("acceptance_id", sa.Integer(), nullable=True),
        sa.Column("uploaded_by", sa.Integer(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("deleted_by", sa.Integer(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["asset_cards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["acceptance_id"], ["asset_acceptances.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_asset_attachments_asset_id", "asset_attachments", ["asset_id"])

    op.create_table(
        "asset_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_no", sa.String(32), nullable=False),
        sa.Column("batch_type", sa.String(16), nullable=False),
        sa.Column("total_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_value", sa.Numeric(14, 2), nullable=True),
        sa.Column("note", sa.String(256), server_default="", nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("batch_no", name="uq_asset_batches_no"),
    )
    op.create_index("ix_asset_batches_batch_no", "asset_batches", ["batch_no"])

    op.create_table(
        "asset_sync_selections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("selection_batch_no", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("selected_by", sa.Integer(), nullable=True),
        sa.Column("selected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("cancelled_by", sa.Integer(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["asset_cards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["selected_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_asset_sync_selections_asset_id", "asset_sync_selections", ["asset_id"])
    op.create_index(
        "ix_asset_sync_selections_selection_batch_no",
        "asset_sync_selections", ["selection_batch_no"],
    )

    op.add_column("asset_cards", sa.Column("batch_no", sa.String(32), nullable=True))
    op.add_column("asset_cards", sa.Column("acceptance_id", sa.Integer(), nullable=True))
    op.add_column("asset_cards", sa.Column("is_booked", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("asset_cards", sa.Column("booked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("asset_cards", sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("asset_cards", sa.Column("is_idle", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("asset_cards", sa.Column("idle_reason", sa.String(128), nullable=True))
    op.create_index("ix_asset_cards_batch_no", "asset_cards", ["batch_no"])
    op.create_index("ix_asset_cards_acceptance_id", "asset_cards", ["acceptance_id"])
    op.create_foreign_key(
        "fk_asset_cards_acceptance_id", "asset_cards", "asset_acceptances",
        ["acceptance_id"], ["id"], ondelete="SET NULL",
    )

    _seed_params()


def _seed_params() -> None:
    params = sa.table(
        "asset_params",
        sa.column("key", sa.String), sa.column("value", sa.String),
        sa.column("value_type", sa.String), sa.column("description", sa.String),
    )
    op.bulk_insert(params, [
        {"key": "asset.idle.days_threshold", "value": "180", "value_type": "number",
         "description": "闲置识别:长期未使用天数阈值(天),默认 180 天,可配置(#14)"},
        {"key": "asset.idle.no_custodian", "value": "true", "value_type": "boolean",
         "description": "闲置识别:无领用人/保管人是否计入闲置(#14)"},
        {"key": "asset.idle.over_config_std", "value": "", "value_type": "string",
         "description": "闲置识别:超配置标准,格式如 A0203:5,A0501:20(同一分类+管理部门件数上限),"
                        "为空表示不启用该规则(#14)"},
    ])


def downgrade() -> None:
    op.drop_constraint("fk_asset_cards_acceptance_id", "asset_cards", type_="foreignkey")
    op.drop_index("ix_asset_cards_acceptance_id", table_name="asset_cards")
    op.drop_index("ix_asset_cards_batch_no", table_name="asset_cards")
    op.drop_column("asset_cards", "idle_reason")
    op.drop_column("asset_cards", "is_idle")
    op.drop_column("asset_cards", "last_used_at")
    op.drop_column("asset_cards", "booked_at")
    op.drop_column("asset_cards", "is_booked")
    op.drop_column("asset_cards", "acceptance_id")
    op.drop_column("asset_cards", "batch_no")
    op.drop_table("asset_sync_selections")
    op.drop_table("asset_batches")
    op.drop_table("asset_attachments")
    op.drop_table("asset_acceptances")
    conn = op.get_bind()
    conn.execute(sa.text(
        "DELETE FROM asset_params WHERE key IN "
        "('asset.idle.days_threshold','asset.idle.no_custodian','asset.idle.over_config_std')"
    ))
