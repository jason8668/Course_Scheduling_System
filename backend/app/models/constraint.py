"""排课约束设置(architecture.md §3.2 软约束权重与可调参数)。

以 key/value 存放而非固定栏位:软约束会随版本增减,加一条约束不该要一次迁移。
未设置的 key 一律回退 `app.solver.problem.SolverConfig` 的默认值。
权重 0 = 关闭该项软约束。设置 UI 于 v2 才做(tasks.md M3-3)。
"""

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ConstraintConfig(Base):
    __tablename__ = "constraint_configs"
    __table_args__ = (
        UniqueConstraint("semester_id", "key", name="uq_constraint_configs_semester_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(40))
    value: Mapped[int] = mapped_column(Integer)
