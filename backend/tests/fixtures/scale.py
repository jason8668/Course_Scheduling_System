"""大规模效能资料集(M5-0):~60 班的初中,供 M5-1「60 班批次导出 < 60 秒」与
M5-4 压测共用。

重点是**量**而非严格教学合理性:班级数、配课数、教师负载大致均衡即可,不保证可完全排课
(可排性由三套学制 fixtures 保证)。教师以「最少负载优先」贪婪指派,让总课时大致平均。
"""

from sqlalchemy.orm import Session

from ._common import Builder, Fixture

# 标准初中每周课程(科目, 每周节数),合计 30 节
_CURRICULUM: list[tuple[str, int]] = [
    ("国文", 5), ("英语", 4), ("数学", 4), ("自然", 4), ("社会", 4),
    ("体育", 2), ("艺术", 2), ("音乐", 1), ("综合", 2), ("信息", 1), ("健康", 1),
]


def build_large_school(
    db: Session, *, academic_year: int = 120, term: int = 1, num_classes: int = 60
) -> Fixture:
    """建一所 num_classes 班的初中(默认 60 班)。"""
    b = Builder(db, academic_year, term, "junior_high")

    for name, _ in _CURRICULUM:
        b.subject(name)

    base = 20
    periods_per_class = sum(p for _, p in _CURRICULUM)
    total_periods = num_classes * periods_per_class
    teacher_names = [f"t{i:03d}" for i in range(max(1, total_periods // 18))]
    for tn in teacher_names:
        b.teacher(tn, base_periods=base)
    load = dict.fromkeys(teacher_names, 0)

    def pick(periods: int) -> str:
        """挑一位加上这几节后仍不超过 base 的教师(最少负载优先);都不合就多聘一位。"""
        fit = [n for n in teacher_names if load[n] + periods <= base]
        if not fit:
            n = f"t{len(teacher_names):03d}"
            b.teacher(n, base_periods=base)
            teacher_names.append(n)
            load[n] = 0
            fit = [n]
        chosen = min(fit, key=lambda n: load[n])
        load[chosen] += periods
        return chosen

    b.room("体育馆", capacity=200)
    b.room("自然实验室", capacity=40)

    # 班级:三个年级平均分配
    per_grade = num_classes // 3
    remainder = num_classes % 3
    made = 0
    for gi, grade in enumerate((7, 8, 9)):
        count = per_grade + (1 if gi < remainder else 0)
        for k in range(count):
            cls = f"{grade}{k + 1:02d}"
            b.klass(cls, grade=grade, track="junior_high")
            for subject, periods in _CURRICULUM:
                b.assign(subject=subject, teachers=[pick(periods)], periods=periods, classes=[cls])
            made += 1

    assert made == num_classes
    return b.build()
