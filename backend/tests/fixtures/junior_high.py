"""junior_high_mid:初中 12 班(七/八/九年级各 4 班)。

特征(tasks.md 测试策略总则):
- **领域课程**:语文/英语/数学/科学/历史与社会/体育与健康/艺术/综合实践活动/信息科技
- **校本课程**:校本课程每班 3 节
- **兼行政减课教师**:教学组长(减 6 节)、训育组长(减 4 节),配课量相应减少
- **场地绑定**:体育与健康 → 操场/体育馆;信息科技 → 电脑教室甲/乙

每班 33 节,可排格数 35(每日 7 节一般课 × 5 天)。
"""

from sqlalchemy.orm import Session

from app.models.basedata import ClassTrack, RoomType

from ._common import Builder, Fixture

CLASS_NAMES = [
    "701", "702", "703", "704",
    "801", "802", "803", "804",
    "901", "902", "903", "904",
]

# 科目 → (每班节数, 任教教师姓名清单)
# 每位教师轮流认养班级(round-robin),故各科教师数决定其每人配课量。
SUBJECT_PLAN: dict[str, tuple[int, list[str]]] = {
    "语文":       (5, ["周淑贞", "许家豪", "彭丽云"]),                    # 4 班 × 5 = 20 节
    "英语":       (4, ["何美惠", "简佩玲", "傅冠廷"]),                    # 4 班 × 4 = 16 节
    "数学":       (4, ["曾国强", "杨子萱", "廖俊宏", "邱雅琪"]),           # 3 班 × 4 = 12 节
    "科学":   (3, ["宋建志", "范文君"]),                              # 6 班 × 3 = 18 节
    "历史与社会":       (3, ["石清雄", "洪淑娟"]),
    "体育与健康": (3, ["卢志豪", "马俊杰"]),
    "艺术":       (3, ["方雅雯", "潘俐君", "杜秉谚"]),                    # 4 班 × 3 = 12 节
    "综合实践活动":   (3, ["庄惠敏", "施泓宇"]),
    "信息科技":       (2, ["连文彬", "唐立群"]),                              # 6 班 × 2 = 12 节
    "校本课程":   (3, ["温子涵", "纪胜文"]),
}

# 兼行政教师:配课量已在 SUBJECT_PLAN 以「多分几位教师」压低,故仍不超课时
ADMIN_TEACHERS = {
    "曾国强": ("教学组长", 6),   # 基本 20 − 减 6 = 应授 14;实配 12
    "方雅雯": ("训育组长", 4),   # 基本 20 − 减 4 = 应授 16;实配 12
}

# 场地绑定:同一位教师的班级集中在同一场地,避免场地需求超过供给
ROOM_BY_TEACHER = {
    "卢志豪": "操场",
    "马俊杰": "体育馆",
    "连文彬": "电脑教室甲",
    "唐立群": "电脑教室乙",
}
ROOM_TYPE_BY_SUBJECT = {
    "体育与健康": RoomType.outdoor,
    "信息科技": RoomType.special,
    "艺术": RoomType.special,  # 未绑定场地,由排课引擎自专科教室中指派
}


def build_junior_high_mid(db: Session, academic_year: int = 115, term: int = 1) -> Fixture:
    b = Builder(db, academic_year, term, "junior_high")

    for subject, room_type in ROOM_TYPE_BY_SUBJECT.items():
        b.subject(subject, required_room_type=room_type)

    for subject, (_periods, names) in SUBJECT_PLAN.items():
        for name in names:
            title, reduction = ADMIN_TEACHERS.get(name, (None, 0))
            b.teacher(
                name,
                base_periods=20,
                admin_title=title,
                admin_reduction=reduction,
                subjects=[subject],
            )

    # 班主任 12 位取自语文/英语/数学/科学教师(3+3+4+2)
    homerooms = (
        SUBJECT_PLAN["语文"][1]
        + SUBJECT_PLAN["英语"][1]
        + SUBJECT_PLAN["数学"][1]
        + SUBJECT_PLAN["科学"][1]
    )
    for cname, homeroom in zip(CLASS_NAMES, homerooms, strict=True):
        b.klass(
            cname,
            grade=int(cname[0]) + 6,  # 701 → 7 年级
            track=ClassTrack.junior_high.value,
            student_count=29,
            homeroom=homeroom,
        )
        b.room(f"{cname}教室", room_type=RoomType.normal, capacity=32)

    b.room("操场", room_type=RoomType.outdoor, capacity=200, subjects=["体育与健康"])
    b.room("体育馆", room_type=RoomType.outdoor, capacity=150, subjects=["体育与健康"])
    b.room("电脑教室甲", room_type=RoomType.special, capacity=35, subjects=["信息科技"])
    b.room("电脑教室乙", room_type=RoomType.special, capacity=35, subjects=["信息科技"])
    b.room("音乐教室", room_type=RoomType.special, capacity=35, subjects=["艺术"])
    b.room("美术教室", room_type=RoomType.special, capacity=35, subjects=["艺术"])
    b.room("理化实验室", room_type=RoomType.special, capacity=32, subjects=["科学"])

    for subject, (periods, names) in SUBJECT_PLAN.items():
        for idx, cname in enumerate(CLASS_NAMES):
            teacher = names[idx % len(names)]
            b.assign(
                subject=subject,
                teachers=[teacher],
                periods=periods,
                classes=[cname],
                room=ROOM_BY_TEACHER.get(teacher),
                required_room_type=ROOM_TYPE_BY_SUBJECT.get(subject),
                lock_room=teacher in ROOM_BY_TEACHER,
            )

    return b.build()
