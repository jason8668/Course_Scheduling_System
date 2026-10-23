"""vocational_high:技高 15 班 3 科(机械/电机/信息,每科 5 班)。

特征(tasks.md 测试策略总则):
- **3 连堂实习**:实习工场每班每周 6 节 = 3 连堂 × 2 次(block_rule)
- **实习工场**:每科 2 座工场,班级固定绑定,容量 30 人
- **业界师资**:每科 1 位外聘,仅周二/周四到校(其余日全为 unavailable 硬约束)
- **协同教学**:三年级实习由业界师资主教 + 校内实习教师协同
- **跑班群组**:二年级 6 班(跨 3 科)组成「二年级多元选修」,群组内 5 门选修
  同时段开课,学生跑班

每班 35 节,可排格数 40(每日 8 节一般课 × 5 天)。
"""

from sqlalchemy.orm import Session

from app.models.basedata import ClassTrack, RoomType

from ._common import Builder, Fixture

DEPARTMENTS = ["机械科", "电机科", "信息科"]
# 每科的班级:(班名后缀, 年级)
CLASS_SUFFIXES = [("一甲", 1), ("一乙", 1), ("二甲", 2), ("二乙", 2), ("三甲", 3)]

# 部定共同科目 → (每班节数, 教师数)。教师以 round-robin 认养 15 个班。
COMMON_SUBJECTS: dict[str, tuple[int, int]] = {
    "国文": (4, 4),
    "英文": (4, 4),
    "数学": (4, 4),
    "体育": (2, 2),
    "弹性学习": (2, 2),
}

# 群科专业科目:一/三年级 7 节、二年级 4 节(二年级以多元选修补足)
# 跑班群组的 5 门选修 → 任教教师(取自共同科目教师中负担较轻者)
ELECTIVES = {
    "机器人程序设计": "国文师4",
    "电子商务实务": "英文师4",
    "生活科技应用": "数学师4",
    "桌球专项": "体育师2",
    "日语会话": "弹性学习师2",
}

GROUP_NAME = "二年级多元选修"
EXTERNAL_TEACHER_DAYS = [2, 4]  # 业界师资到校日:周二、周四


def _common_teacher_name(subject: str, idx: int) -> str:
    return f"{subject}师{idx + 1}"


def build_vocational_high(db: Session, academic_year: int = 115, term: int = 1) -> Fixture:
    b = Builder(db, academic_year, term, "vocational")

    b.subject("实习工场", required_room_type=RoomType.workshop, default_block_size=3)
    b.subject("体育", required_room_type=RoomType.outdoor)
    for elective in ELECTIVES:
        b.subject(elective, domain="多元选修")

    # ── 共同科目教师 ──
    for subject, (_periods, count) in COMMON_SUBJECTS.items():
        for i in range(count):
            b.teacher(_common_teacher_name(subject, i), base_periods=20, subjects=[subject])

    # ── 场地 ──
    b.room("操场", room_type=RoomType.outdoor, capacity=200, subjects=["体育"])
    for dept in DEPARTMENTS:
        for wing in ("A", "B"):
            b.room(
                f"{dept}工场{wing}",
                room_type=RoomType.workshop,
                capacity=30,
                subjects=["实习工场"],
            )

    # ── 各科教师、班级、专业配课 ──
    for dept in DEPARTMENTS:
        short = dept[:2]  # 机械 / 电机 / 信息
        prof = [f"{short}专业师{i + 1}" for i in range(4)]
        practicum = [f"{short}实习师{i + 1}" for i in range(2)]
        external = f"{short}业界师"

        for name in prof + practicum:
            b.teacher(name, base_periods=20, subjects=["专业实习", "群科专业科目"])
        # 业界师资:基本课时低、仅周二/周四到校
        b.teacher(external, base_periods=6, is_external=True, subjects=["实习工场"])
        b.unavailable_days(external, [d for d in range(1, 6) if d not in EXTERNAL_TEACHER_DAYS])

        classes = [f"{short}{suffix}" for suffix, _grade in CLASS_SUFFIXES]
        homeroom_pool = prof + practicum  # 6 位,足够让 5 班各有专属导师
        for i, ((_suffix, grade), cname) in enumerate(zip(CLASS_SUFFIXES, classes, strict=True)):
            b.klass(
                cname,
                grade=grade,
                track=ClassTrack.vocational.value,
                department=dept,
                student_count=30,
                homeroom=homeroom_pool[i],
            )
            b.room(f"{cname}教室", room_type=RoomType.normal, capacity=32)

        c1, c2, c3, c4, c5 = classes  # 一甲 一乙 二甲 二乙 三甲

        # 专业实习 6 节/班:专业师1 带 3 班(18 节)、专业师2 带 2 班(12 节)
        b.assign(subject="专业实习", teachers=[prof[0]], periods=6, classes=[c1, c2, c3])
        b.assign(subject="专业实习", teachers=[prof[1]], periods=6, classes=[c4, c5])

        # 群科专业科目:专业师3 带一年级(各 7 节=14)、专业师4 带二三年级(7+4+4=15)
        b.assign(subject="群科专业科目", teachers=[prof[2]], periods=7, classes=[c1, c2])
        b.assign(subject="群科专业科目", teachers=[prof[3]], periods=7, classes=[c5])
        b.assign(subject="群科专业科目", teachers=[prof[3]], periods=4, classes=[c3, c4])

        # 实习工场 6 节 = 3 连堂 × 2;一甲/一乙/二甲在工场A,二乙/三甲在工场B
        for cname, teacher, wing in (
            (c1, practicum[0], "A"),
            (c2, practicum[0], "A"),
            (c3, practicum[1], "A"),
            (c4, practicum[1], "B"),
        ):
            b.assign(
                subject="实习工场",
                teachers=[teacher],
                periods=6,
                classes=[cname],
                room=f"{dept}工场{wing}",
                required_room_type=RoomType.workshop,
                blocks=(3, 2),
                lock_room=True,
            )
        # 三年级:业界师资主教 + 校内实习师2 协同
        b.assign(
            subject="实习工场",
            teachers=[external, practicum[1]],
            periods=6,
            classes=[c5],
            room=f"{dept}工场B",
            required_room_type=RoomType.workshop,
            blocks=(3, 2),
            lock_room=True,
        )

    # ── 共同科目:15 班 round-robin ──
    all_classes = list(b.classes)
    for subject, (periods, count) in COMMON_SUBJECTS.items():
        for idx, cname in enumerate(all_classes):
            b.assign(
                subject=subject,
                teachers=[_common_teacher_name(subject, idx % count)],
                periods=periods,
                classes=[cname],
                room="操场" if subject == "体育" else None,
                required_room_type=RoomType.outdoor if subject == "体育" else None,
            )

    # ── 跑班群组:二年级 6 班(跨 3 科),5 门选修同时段开课 ──
    g2_classes = [f"{d[:2]}{suffix}" for d in DEPARTMENTS for suffix, grade in CLASS_SUFFIXES
                  if grade == 2]
    b.group(GROUP_NAME, g2_classes)
    for elective, teacher in ELECTIVES.items():
        b.assign(subject=elective, teachers=[teacher], periods=3, group=GROUP_NAME)

    return b.build()
