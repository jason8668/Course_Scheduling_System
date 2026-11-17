"""#83:资产 7 类扫描定时任务(每日 08:00)与预约释放钉钉推送。

SQLite 环境跑真实扫描函数;Redis/RQ 只以假伫列验证排入逻辑。
钉钉推送以 monkeypatch 截获,不真的发钉钉。
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.asset_approval import ApprovalInstance
from app.models.asset_card import AssetCard
from app.models.asset_circulation import (
    AssetBorrowOrder,
    AssetHandoverOrder,
    AssetReminder,
    AssetReservation,
    BorrowStatusDoc,
    HandoverStatus,
    ReservationStatus,
)
from app.models.asset_inventory import (
    AssetInventoryPlan,
    AssetInventoryTask,
    InventoryTaskStatus,
)
from app.models.asset_ledger import AssetSyncSelection
from app.models.user import Role
from app.services.asset_seed import seed_asset_foundation
from app.services.users import create_user
from app.workers import asset_scan_job as scan_job


@pytest.fixture
def seeded_db(db):
    """种子 + 用户 + 7 类扫描各一笔到期/逾期资料。"""
    seed_asset_foundation(db)
    users = {}
    for username, roles in [
        ("adm", [Role.admin]),
        ("am", [Role.asset_admin]),
        ("tea", [Role.teacher]),
        ("tea2", [Role.teacher]),
    ]:
        users[username] = create_user(
            db, username=username, password="pw-123456", roles=list(roles),
            must_change_password=False,
        )
    db.commit()
    tea, tea2 = users["tea"], users["tea2"]
    now = datetime.now(UTC)
    card = AssetCard(
        asset_code="ZC-TEST-001", label_code="ZC-TEST-001-0",
        name="测试资产", category_code="A0203",
        custodian_user_id=tea.id, custodian_name="tea",
        ext={"warranty_until": (now + timedelta(days=10)).date().isoformat()},
    )
    db.add(card)
    db.flush()
    db.add(AssetBorrowOrder(
        doc_no="JY-20260101-0001", asset_id=card.id, borrower_id=tea.id,
        borrower_name="tea", due_at=now - timedelta(days=2),
        status=BorrowStatusDoc.BORROWING,
    ))
    db.add(AssetHandoverOrder(
        doc_no="YJ-20260101-0001", from_user_id=tea.id, from_user_name="tea",
        to_user_id=tea2.id, to_user_name="tea2",
        status=HandoverStatus.PENDING,
        created_at=now - timedelta(days=10),
    ))
    db.add(AssetReservation(
        doc_no="YY-20260101-0001", asset_id=card.id, reserver_id=tea.id,
        reserver_name="tea", start_at=now - timedelta(hours=2),
        end_at=now - timedelta(hours=1), status=ReservationStatus.PENDING,
    ))
    db.add(ApprovalInstance(
        flow_id=1, doc_type="借用单", doc_id=1, doc_no="JY-20260101-0001",
        applicant_id=tea.id, applicant_name="tea",
        status="进行中", is_overdue=True, current_step=1,
    ))
    plan = AssetInventoryPlan(plan_no="PD-20260101-0001", name="测试盘点")
    db.add(plan)
    db.flush()
    db.add(AssetInventoryTask(
        plan_id=plan.id, assignee_id=tea.id, assignee_name="tea",
        due_at=now - timedelta(days=1), status=InventoryTaskStatus.PENDING,
    ))
    db.add(AssetSyncSelection(
        asset_id=card.id, selection_batch_no="GX-20260101-0001",
        status="active", selected_by=users["am"].id,
        selected_at=now - timedelta(days=20),
    ))
    db.commit()
    return db, users, card


@pytest.fixture
def no_dingtalk(monkeypatch):
    """截获全部钉钉推送(单人 + 按角色),记下呼叫,不真的发钉钉。"""
    calls: list[dict] = []

    def fake_push_to_user(db, user_id, title, text):
        calls.append({"kind": "user", "user_id": user_id, "title": title, "text": text})
        return {"sent": 0, "skipped": 1, "failed": 0}

    def fake_push_to_role(db, role, title, text):
        calls.append({"kind": "role", "role": role, "title": title, "text": text})
        return {"sent": 0, "skipped": 1, "failed": 0}

    monkeypatch.setattr("app.services.asset_notify.push_to_user", fake_push_to_user)
    monkeypatch.setattr("app.services.asset_notify.push_to_role", fake_push_to_role)
    return calls


# ── 7 类扫描全跑通 ──────────────────────────────────────────
def test_asset_scan_job_runs_all_seven(seeded_db, no_dingtalk):
    db, users, card = seeded_db
    tea = users["tea"]

    results = scan_job.run_asset_scans(db)

    assert sorted(results) == [
        "approval_overdue", "borrow_overdue", "handover_warnings",
        "inventory_due", "reservation_release", "sync_backlog", "warranty",
    ]
    assert all(v["ok"] for v in results.values()), results
    # 各类扫描的实际效果
    borrow = db.query(AssetBorrowOrder).first()
    assert borrow.status == BorrowStatusDoc.OVERDUE
    assert borrow.is_overdue is True
    assert db.query(AssetHandoverOrder).first().is_overdue is True
    res = db.query(AssetReservation).first()
    assert res.status == ReservationStatus.RELEASED
    assert res.released_at is not None
    assert db.query(AssetInventoryTask).first().id in (
        results["inventory_due"]["result"]["reminded_tasks"])
    assert results["sync_backlog"]["result"]["reminded_batches"] == ["GX-20260101-0001"]
    assert results["warranty"]["result"]["reminded"] == [card.id]
    assert db.query(AssetReminder).count() >= 7
    # 预约释放推送了预约人(此前只写站内提醒,无钉钉)
    release_pushes = [c for c in no_dingtalk
                      if c["kind"] == "user" and c["user_id"] == tea.id
                      and "预约已自动释放" in c["title"]]
    assert len(release_pushes) == 1
    assert "YY-20260101-0001" in release_pushes[0]["title"]
    assert results["reservation_release"]["result"]["pushed"]["skipped"] == 1


def test_reservation_release_pushes_reserver(seeded_db, no_dingtalk):
    """单测预约释放推送:只跑这一类,确认 push_to_user 收到预约人。"""
    from app.services import asset_circulation as circ_svc

    db, users, _card = seeded_db
    tea = users["tea"]

    result = circ_svc.scan_reservation_release(db)

    assert result["released"]
    assert result["pushed"] == {"sent": 0, "skipped": 1, "failed": 0}
    assert any(
        c["kind"] == "user" and c["user_id"] == tea.id
        and c["title"] == "预约已自动释放:YY-20260101-0001"
        for c in no_dingtalk
    )


def test_asset_scan_job_isolates_failures(seeded_db, no_dingtalk, monkeypatch):
    """某类抛错不中断其他类:保修扫描抛错,前后各类照常跑、照常落库。"""
    from app.services import asset_circulation as circ_svc

    db, _users, _card = seeded_db

    def boom(db, user=None):
        raise RuntimeError("保修扫描模拟故障")

    monkeypatch.setattr(circ_svc, "scan_warranty", boom)

    results = scan_job.run_asset_scans(db)

    assert results["warranty"]["ok"] is False
    assert "模拟故障" in results["warranty"]["error"]
    for name in ("borrow_overdue", "handover_warnings", "reservation_release",
                 "approval_overdue", "inventory_due", "sync_backlog"):
        assert results[name]["ok"] is True, (name, results[name])
    # 排在故障类之后的扫描仍生效(未被中断)
    assert db.query(AssetReservation).first().status == ReservationStatus.RELEASED
    assert results["sync_backlog"]["result"]["reminded_batches"] == ["GX-20260101-0001"]


def test_asset_scan_job_self_renews(seeded_db, no_dingtalk, monkeypatch):
    """RQ 进入点:跑完把下一次排进去(自我续期)。"""
    db, _users, _card = seeded_db
    scheduled: list[bool] = []
    monkeypatch.setattr(
        scan_job, "schedule_asset_scan", lambda: scheduled.append(True))

    results = scan_job.asset_scan_job(db=db)

    assert len(results) == 7
    assert scheduled == [True]


# ── 排程器:固定 job_id、每日 08:00 ─────────────────────────
class _FakeQueue:
    def __init__(self):
        self.calls: list[tuple] = []

    def enqueue(self, fn, *args, **kwargs):
        self.calls.append(("enqueue", fn, kwargs.get("job_id")))

    def enqueue_in(self, delta, fn, *args, **kwargs):
        self.calls.append(("enqueue_in", delta, fn, kwargs.get("job_id")))

    def enqueue_at(self, when, fn, *args, **kwargs):
        self.calls.append(("enqueue_at", when, fn, kwargs.get("job_id")))


class _FakeRegistry:
    def __init__(self, job_ids):
        self._ids = job_ids

    def get_job_ids(self):
        return list(self._ids)

    def remove(self, job_id, delete_job=False):
        self._ids.discard(job_id)


def test_next_asset_scan_time_is_0800():
    from app.workers import scheduler

    nxt = scheduler._next_asset_scan_time()
    assert (nxt.hour, nxt.minute, nxt.second) == (8, 0, 0)
    assert nxt.date() >= datetime.now().date()


def test_schedule_asset_scan_enqueues_at_0800(monkeypatch):
    from app.workers import scheduler

    fake = _FakeQueue()
    monkeypatch.setattr(scheduler, "ops_queue", fake)

    scheduler.schedule_asset_scan()

    assert len(fake.calls) == 1
    kind, when, fn, job_id = fake.calls[0]
    assert kind == "enqueue_at"
    assert job_id == scheduler.ASSET_SCAN_JOB_ID == "asset-daily-scan"
    assert fn is scan_job.asset_scan_job
    assert (when.hour, when.minute) == (8, 0)


def test_ensure_asset_scan_scheduled_repairs_broken_chain(monkeypatch):
    """心跳兜底:注册表里没有 asset-daily-scan 时补排。"""
    from app.workers import scheduler

    fake = _FakeQueue()
    monkeypatch.setattr(scheduler, "ops_queue", fake)
    monkeypatch.setattr(
        scheduler, "ScheduledJobRegistry", lambda queue: _FakeRegistry(set()))

    scheduler._ensure_asset_scan_scheduled()

    assert any(
        c[0] == "enqueue_at" and c[3] == "asset-daily-scan" for c in fake.calls
    )


def test_ensure_scheduled_runs_asset_scan_immediately(monkeypatch):
    """首次排入立即跑一次(验证链路),之后每日 08:00。"""
    from app.workers import scheduler

    fake = _FakeQueue()
    monkeypatch.setattr(scheduler, "ops_queue", fake)
    monkeypatch.setattr(scheduler, "default_queue", fake)
    monkeypatch.setattr(
        scheduler, "ScheduledJobRegistry", lambda queue: _FakeRegistry(set()))

    scheduler.ensure_scheduled()

    immediate = [c for c in fake.calls
                 if c[0] == "enqueue" and c[2] == "asset-daily-scan"]
    assert len(immediate) == 1
    assert immediate[0][1] is scan_job.asset_scan_job
    # 原有五类任务的排入不受影响
    job_ids = {c[-1] for c in fake.calls}
    assert {"scheduler-heartbeat", "daily-backup", "class-reminder",
            "holiday-sync", "monthly-hours"} <= job_ids
