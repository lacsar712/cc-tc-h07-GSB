import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import claimer
from claimer import settle
from models import Base, ConvergenceLog, row_dict
from rules import LIMIT_MM, judge


class TestJudge:
    @pytest.mark.parametrize("v", [0.0, 1.2, -1.2, 2.9, -2.9, 3.0, -3.0])
    def test_within_limit_is_qualified(self, v):
        verdict, reason = judge(v)
        assert verdict == "合格"
        assert str(LIMIT_MM) in reason

    @pytest.mark.parametrize("v", [3.1, -3.1, 5.6, -7.7])
    def test_beyond_limit_is_over(self, v):
        verdict, _ = judge(v)
        assert verdict == "超限"


class TestSettle:
    def test_in_limit_lands_done_qualified(self):
        status, verdict, reason = settle(1.2)
        assert status == "done"
        assert verdict == "合格"
        assert reason

    def test_over_limit_lands_done_over(self):
        status, verdict, _ = settle(5.6)
        assert (status, verdict) == ("done", "超限")

    @pytest.mark.parametrize("v", [-7.7, -3.0, -1.2, 0.0, 2.9, 3.0, 3.1, 5.6])
    def test_never_half_state(self, v):
        # 够线必须落合格、超线落超限，任何读数都不许停在 pending/空结论的半态
        status, verdict, reason = settle(v)
        assert status == "done"
        assert verdict in ("合格", "超限")
        assert reason


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/t.db")
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)
    monkeypatch.setattr(claimer, "SessionLocal", TestingSession)
    yield TestingSession


def _pending_row(chainage, delta_mm):
    return ConvergenceLog(
        chainage=chainage,
        delta_mm=delta_mm,
        status="pending",
        created_by="surveyor",
        created_at=datetime.now(timezone.utc),
    )


class TestClaimOnce:
    def test_writes_terminal_verdict_and_mm_stays(self, db_session):
        db = db_session()
        db.add(_pending_row("K20+050", 2.4))
        db.commit()
        db.close()

        assert claimer.claim_once() is True

        db = db_session()
        row = db.query(ConvergenceLog).one()
        assert row.status == "done"
        assert row.verdict == "合格"
        assert row.delta_mm == 2.4
        assert row.reason
        assert row.processed_at is not None
        db.close()

        # 已落终态，不会被重复认领改写
        assert claimer.claim_once() is False

    def test_face_reading_goes_through_same_judgment(self, db_session):
        # 掌子面附近读数同样走这份判定，无特例
        db = db_session()
        db.add(_pending_row("掌子面 K21+300", 3.0))
        db.add(_pending_row("掌子面 K21+320", 3.1))
        db.commit()
        db.close()

        assert claimer.claim_once() is True
        assert claimer.claim_once() is True

        db = db_session()
        rows = db.query(ConvergenceLog).order_by(ConvergenceLog.id).all()
        assert [(r.status, r.verdict) for r in rows] == [
            ("done", "合格"),
            ("done", "超限"),
        ]
        db.close()


def test_row_dict_carries_mm_and_verdict_together():
    # 界面读数：结论与毫米值必须同时在，不允许结论亮了毫米却缺
    now = datetime.now(timezone.utc)
    row = ConvergenceLog(
        id=1,
        chainage="K12+180",
        delta_mm=1.2,
        status="done",
        verdict="合格",
        reason="收敛 1.2 mm 在 ±3.0 mm 以内",
        created_by="surveyor",
        created_at=now,
        processed_at=now,
    )
    d = row_dict(row)
    assert d["delta_mm"] == 1.2
    assert d["verdict"] == "合格"
    assert d["status"] == "done"
    assert d["reason"]
