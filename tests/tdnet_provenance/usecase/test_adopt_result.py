import datetime
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from buyback_analysis.models.base import Base
from midterm_plan_analysis.models.midterm_plan import MidtermPlan
from midterm_plan_analysis.models.midterm_plan_keyword import MidtermPlanKeyword
from tdnet_provenance.models.base import ProvenanceBase
from tdnet_provenance.models.result_adoption import ResultAdoption
from tdnet_provenance.models.result_version import ResultVersion
from tdnet_provenance.usecase.adopt_result import (
    adopt_result,
    current_is_failed,
    require_provenance_for_rerun,
    snapshot_current,
    write_failure_placeholder,
)

URL = "https://www.release.tdnet.info/inbs/140120260218512345.pdf"
TABLES = (MidtermPlan, MidtermPlanKeyword)
NOW = datetime.datetime(2026, 2, 19, 8, 0, tzinfo=datetime.timezone.utc)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine, tables=[MidtermPlan.__table__, MidtermPlanKeyword.__table__])
    ProvenanceBase.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False, future=True)() as s:
        yield s


def _plan(name, status="ok"):
    return MidtermPlan(code="1234", url=URL, plan_name=name, disclosure_date="2026-02-19", extraction_status=status)


def _writer(session, name, status="ok", keywords=()):
    def write():
        session.add(_plan(name, status))
        for kw in keywords:
            session.add(MidtermPlanKeyword(code="1234", url=URL, keyword=kw, disclosure_date="2026-02-19"))
        session.flush()
        return True

    return write


def _adopt(session, write, **overrides):
    kwargs = dict(
        result_type="midterm_plan", tables=TABLES, url=URL, code="1234", extraction_status="ok",
        run_ids=["run-1"], write_current=write, clock=lambda: NOW,
    )
    kwargs.update(overrides)
    return adopt_result(session, **kwargs)


def _versions(session):
    return session.query(ResultVersion).order_by(ResultVersion.origin).all()


def test_new_url_creates_run_version_and_adoption(session):
    assert _adopt(session, _writer(session, "新計画", keywords=["DX"])) is True

    [version] = _versions(session)
    assert version.origin == "run"
    assert json.loads(version.run_ids) == ["run-1"]
    payload = json.loads(version.payload)
    assert payload["midterm_plans"][0]["plan_name"] == "新計画"
    assert [k["keyword"] for k in payload["midterm_plan_keywords"]] == ["DX"]
    [adoption] = session.query(ResultAdoption).all()
    assert adoption.version_id == version.version_id
    assert adoption.adopted_at == NOW.isoformat()
    assert session.query(MidtermPlan).one().plan_name == "新計画"


def test_rerun_preserves_existing_rows_as_legacy_version(session):
    session.add(_plan("旧計画"))
    session.add(MidtermPlanKeyword(code="1234", url=URL, keyword="旧KW"))
    session.commit()

    assert _adopt(session, _writer(session, "新計画")) is True

    legacy, run = _versions(session)
    assert legacy.origin == "legacy" and json.loads(legacy.run_ids) == []
    assert json.loads(legacy.payload)["midterm_plans"][0]["plan_name"] == "旧計画"
    assert [k["keyword"] for k in json.loads(legacy.payload)["midterm_plan_keywords"]] == ["旧KW"]
    assert run.origin == "run"
    # legacy版は採用時刻が分からないため採用行を作らない
    assert [a.version_id for a in session.query(ResultAdoption).all()] == [run.version_id]
    assert session.query(MidtermPlan).one().plan_name == "新計画"
    assert session.query(MidtermPlanKeyword).count() == 0


def test_second_rerun_does_not_snapshot_legacy_again(session):
    session.add(_plan("旧計画"))
    session.commit()
    _adopt(session, _writer(session, "1回目"))
    _adopt(session, _writer(session, "2回目"))

    origins = sorted(v.origin for v in _versions(session))
    assert origins == ["legacy", "run", "run"]
    assert session.query(ResultAdoption).count() == 2
    assert session.query(MidtermPlan).one().plan_name == "2回目"


def test_failed_only_rows_are_not_snapshotted(session):
    session.add(_plan(None, status="failed"))
    session.commit()
    _adopt(session, _writer(session, "新計画"))
    assert [v.origin for v in _versions(session)] == ["run"]


@pytest.mark.parametrize("failure", ["returns_false", "raises"])
def test_write_failure_keeps_previous_adoption(session, failure):
    session.add(_plan("旧計画"))
    session.commit()

    def broken():
        session.add(_plan("途中まで"))
        if failure == "raises":
            raise RuntimeError("database is locked")
        return False

    assert _adopt(session, broken) is False

    assert session.query(MidtermPlan).one().plan_name == "旧計画"
    assert session.query(ResultVersion).count() == 0
    assert session.query(ResultAdoption).count() == 0


def test_append_without_replacing(session):
    session.add(_plan("既存計画"))
    session.commit()

    def add_keywords():
        session.add(MidtermPlanKeyword(code="1234", url=URL, keyword="新KW"))
        session.flush()
        return True

    assert _adopt(session, add_keywords, replace_current=False) is True
    assert session.query(MidtermPlan).one().plan_name == "既存計画"
    run = [v for v in _versions(session) if v.origin == "run"][0]
    payload = json.loads(run.payload)
    assert payload["midterm_plans"][0]["plan_name"] == "既存計画"
    assert [k["keyword"] for k in payload["midterm_plan_keywords"]] == ["新KW"]


def test_failure_placeholder_written_only_without_current_rows(session):
    calls = []
    assert write_failure_placeholder(session, tables=TABLES, url=URL, write_failed=lambda: calls.append(1) or True)
    assert calls == [1]

    session.add(_plan("旧計画"))
    session.commit()
    assert write_failure_placeholder(session, tables=TABLES, url=URL, write_failed=lambda: calls.append(2) or True)
    assert calls == [1]  # 現行行があれば旧採用を維持して書かない


def test_current_is_failed(session):
    assert current_is_failed(session, TABLES, URL) is False
    session.add(_plan(None, status="failed"))
    session.commit()
    assert current_is_failed(session, TABLES, URL) is True


def test_snapshot_excludes_autoincrement_id(session):
    session.add(MidtermPlanKeyword(code="1234", url=URL, keyword="KW"))
    session.commit()
    assert "id" not in snapshot_current(session, TABLES, URL)["midterm_plan_keywords"][0]


def test_rerun_requires_provenance():
    with pytest.raises(RuntimeError, match="TDNET_PROVENANCE_ENABLED"):
        require_provenance_for_rerun(None, ["https://x/a.pdf"])
    require_provenance_for_rerun(None, [])
    require_provenance_for_rerun(object(), ["https://x/a.pdf"])
