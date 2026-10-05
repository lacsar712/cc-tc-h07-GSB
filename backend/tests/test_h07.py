"""H07 回归：判定够线必须落合格、不得停在半态；巡检员禁写、测量岗可送单。"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import claimer
import models
from rules import LIMIT_MM, judge


def test_within_limit_is_qualified():
    for delta in (0.0, 1.2, -2.9, LIMIT_MM, -LIMIT_MM):
        verdict, _ = judge(delta)
        assert verdict == "合格", delta


def test_beyond_limit_is_over_limit():
    for delta in (3.1, -3.1, 5.6, -7.0):
        verdict, _ = judge(delta)
        assert verdict == "超限", delta


def _claim_in_isolated_db(monkeypatch, tmp_path, delta_mm):
    """把认领线程指到独立 SQLite 库，登记一行待判记录。"""
    engine = create_engine(f"sqlite:///{tmp_path}/claim.db")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(claimer, "SessionLocal", Session)

    db = Session()
    row = models.ConvergenceLog(
        chainage="K20+050",
        delta_mm=delta_mm,
        status="pending",
        created_by="surveyor",
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    row_id = row.id
    db.close()
    return Session, row_id


@pytest.mark.parametrize(
    "delta_mm, expect",
    [(1.8, "合格"), (3.0, "合格"), (-3.0, "合格"), (5.6, "超限"), (-3.1, "超限")],
)
def test_pending_row_lands_done_with_verdict(monkeypatch, tmp_path, delta_mm, expect):
    Session, row_id = _claim_in_isolated_db(monkeypatch, tmp_path, delta_mm)

    assert claimer.claim_once() is True

    db = Session()
    try:
        row = db.get(models.ConvergenceLog, row_id)
        assert row.status == "done"
        assert row.verdict == expect
        assert row.reason
        assert row.processed_at is not None
    finally:
        db.close()


def test_claimed_row_leaves_queue(monkeypatch, tmp_path):
    # 判过的行不得再被认领重算：不允许停在半态
    Session, _ = _claim_in_isolated_db(monkeypatch, tmp_path, 2.4)
    assert claimer.claim_once() is True
    assert claimer.claim_once() is False


def test_no_half_state_rows(monkeypatch, tmp_path):
    # 结论与毫米必须同在：done 行不缺结论，pending 行不带结论
    Session, _ = _claim_in_isolated_db(monkeypatch, tmp_path, 0.9)
    claimer.claim_once()
    db = Session()
    try:
        for row in db.query(models.ConvergenceLog).all():
            if row.status == "done":
                assert row.verdict in ("合格", "超限")
                assert row.delta_mm is not None
                assert row.processed_at is not None
            else:
                assert row.verdict is None
    finally:
        db.close()


def test_inspector_read_only_and_surveyor_can_submit():
    try:
        import api
    except Exception:
        pytest.skip("数据库不可用，跳过接口级角色测试")

    client = api.app.test_client()

    anon = client.post("/api/logs", json={"chainage": "K21+000", "delta_mm": 2.0})
    assert anon.status_code == 401

    insp = client.post(
        "/api/auth/login", json={"username": "inspector", "password": "insp123456"}
    )
    assert insp.status_code == 200
    r = client.post(
        "/api/logs",
        json={"chainage": "K21+000", "delta_mm": 2.0},
        headers={"Authorization": f"Bearer {insp.get_json()['access_token']}"},
    )
    assert r.status_code == 403

    surv = client.post(
        "/api/auth/login", json={"username": "surveyor", "password": "surv123456"}
    )
    assert surv.status_code == 200
    r = client.post(
        "/api/logs",
        json={"chainage": "K21+000", "delta_mm": 2.0},
        headers={"Authorization": f"Bearer {surv.get_json()['access_token']}"},
    )
    assert r.status_code == 201

    db = api.SessionLocal()
    try:
        row = db.query(api.ConvergenceLog).filter_by(chainage="K21+000").one()
        assert row.delta_mm == 2.0
        db.delete(row)
        db.commit()
    finally:
        db.close()
