import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from buyback_analysis.models.announcement import Announcement
from buyback_analysis.models.base import Base
from buyback_analysis.models.is_checked import IsChecked
from buyback_analysis.models.progress import Progress
from buyback_analysis.usecase.buyback_result_writer import BUYBACK_TABLES, BuybackResultWriter
from tdnet_provenance.models.base import ProvenanceBase
from tdnet_provenance.models.result_adoption import ResultAdoption
from tdnet_provenance.models.result_version import ResultVersion

URL = "https://www.release.tdnet.info/inbs/140120260218512345.pdf"


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine, tables=[m.__table__ for m in BUYBACK_TABLES])
    ProvenanceBase.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False, future=True)() as s:
        yield s


def _announcement(amount):
    return {"type": "buyback_announcement", "data": {
        "code": "1234", "url": URL, "disclosure_date": "2026-02-19", "buyback_amount_yen": amount,
    }}


def _existing(session):
    """通常処理で保存済みの旧結果を作る。"""
    writer = BuybackResultWriter(session, rerun=False)
    writer.register_type("1234", URL, "buyback_announcement")
    assert writer.save(URL, _announcement(100)) is True
    writer.mark(URL, "saved")


def test_normal_mode_writes_immediately(session):
    _existing(session)
    assert session.query(IsChecked).one().parse_status == "saved"
    assert session.query(Announcement).one().buyback_amount_yen == 100
    assert session.query(ResultVersion).count() == 0


def test_rerun_success_replaces_and_keeps_old_as_legacy(session):
    _existing(session)
    writer = BuybackResultWriter(session, rerun=True)
    writer.register_type("1234", URL, "buyback_announcement")
    assert session.query(IsChecked).one().parse_status == "saved"  # 採用まで書かない

    assert writer.save(URL, _announcement(200)) is True
    writer.mark(URL, "saved")

    assert session.query(Announcement).one().buyback_amount_yen == 200
    checked = session.query(IsChecked).one()
    assert (checked.detected_type, checked.parse_status) == ("buyback_announcement", "saved")
    versions = {v.origin: v for v in session.query(ResultVersion).all()}
    assert json.loads(versions["legacy"].payload)["announcements"][0]["buyback_amount_yen"] == 100
    assert json.loads(versions["unrecorded"].payload)["announcements"][0]["buyback_amount_yen"] == 200
    assert versions["unrecorded"].extraction_status == "saved"
    assert session.query(ResultAdoption).count() == 1


def test_rerun_failure_keeps_old(session):
    _existing(session)
    writer = BuybackResultWriter(session, rerun=True)
    writer.register_type("1234", URL, "buyback_announcement")
    writer.mark(URL, "failed")

    assert session.query(IsChecked).one().parse_status == "saved"
    assert session.query(Announcement).one().buyback_amount_yen == 100
    assert session.query(ResultVersion).count() == 0


def test_rerun_constraint_violation_keeps_old(session):
    _existing(session)
    writer = BuybackResultWriter(session, rerun=True)
    writer.register_type("1234", URL, "buyback_announcement")
    broken = _announcement(200)
    broken["data"]["code"] = None  # NOT NULL違反は呼び出し側に例外ではなく保存失敗として返る
    broken["data"]["disclosure_date"] = "2026-02-19"
    assert writer.save(URL, broken) is False
    assert session.query(Announcement).one().buyback_amount_yen == 100


def test_rerun_type_change_to_out_of_scope_is_adopted(session):
    _existing(session)
    writer = BuybackResultWriter(session, rerun=True)
    writer.register_type("1234", URL, "other")
    writer.mark(URL, "skipped")

    assert session.query(Announcement).count() == 0
    checked = session.query(IsChecked).one()
    assert (checked.detected_type, checked.parse_status) == ("other", "skipped")
    assert sorted(v.origin for v in session.query(ResultVersion).all()) == ["legacy", "unrecorded"]


def test_rerun_type_change_between_ir_tables(session):
    _existing(session)
    writer = BuybackResultWriter(session, rerun=True)
    writer.register_type("1234", URL, "buyback_progress")
    progress = {"type": "buyback_progress", "data": {"code": "1234", "url": URL, "disclosure_date": "2026-02-19"}}
    assert writer.save(URL, progress) is True
    assert session.query(Announcement).count() == 0
    assert session.query(Progress).count() == 1
