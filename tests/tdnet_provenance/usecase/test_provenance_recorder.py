import datetime
import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from tdnet_provenance.models.base import ProvenanceBase
from tdnet_provenance.models.processing_run import ProcessingRun
from tdnet_provenance.usecase.provenance_recorder import (
    ProvenanceRecorder,
    RunPersistError,
    RunSpec,
    canonical_hash,
    prompt_file_hash,
    run_llm_stage,
)
from tdnet_provenance.usecase.resolve_verified_source import (
    SourceVerificationError,
    VerifiedSource,
)

COMMIT = "0123456789abcdef0123456789abcdef01234567"
URL = "https://www.release.tdnet.info/inbs/140120260218512345.pdf"
NOW = datetime.datetime(2026, 2, 19, 8, 0, tzinfo=datetime.timezone.utc)
SOURCE = VerifiedSource(
    url=URL,
    source_document_id="doc-uuid",
    external_document_id="140120260218512345",
    storage_uri="tdnet-pdf://20260219/140120260218512345.pdf",
    source_hash="a" * 64,
    path=Path("/pdf/20260219/140120260218512345.pdf"),
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    ProvenanceBase.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True)() as s:
        yield s


def _recorder(session, resolver=None):
    return ProvenanceRecorder(session, code_commit=COMMIT, clock=lambda: NOW, resolver=resolver)


def _runs(session):
    return session.query(ProcessingRun).all()


def _run_metrics(recorder, call, **kwargs):
    return recorder.run_llm(
        source=SOURCE, stage="metrics", prompt_name="midterm_plan.md",
        input_payload={"title": "t", "text_sha256": "x"}, call=call, **kwargs,
    )


def test_successful_llm_run_records_source_and_conditions(session):
    result = _run_metrics(_recorder(session), lambda: {"data": {}})

    assert result == {"data": {}}
    [run] = _runs(session)
    assert run.status == "succeeded"
    assert run.run_kind == "extract"
    assert run.stage == "metrics"
    assert run.url == URL
    assert run.source_document_id == "doc-uuid"
    assert run.source_hash == "a" * 64
    assert run.input_locator == SOURCE.storage_uri
    assert run.code_commit == COMMIT
    assert run.extractor_version == COMMIT
    assert run.prompt_name == "midterm_plan.md"
    assert run.prompt_hash == prompt_file_hash("midterm_plan.md")
    assert run.model_provider == "google"
    assert run.model_name
    assert json.loads(run.generation_config) == {}
    assert run.started_at == NOW.isoformat()
    assert run.completed_at == NOW.isoformat()
    assert run.error_code is None
    assert len(run.reuse_key) == 64


def test_input_hash_excludes_pdf_path(session):
    recorder = _recorder(session)
    _run_metrics(recorder, lambda: {})
    moved = VerifiedSource(**{**SOURCE.__dict__, "path": Path("/other/root/x.pdf")})
    recorder.run_llm(
        source=moved, stage="metrics", prompt_name="midterm_plan.md",
        input_payload={"title": "t", "text_sha256": "x"}, call=lambda: {},
    )
    first, second = _runs(session)
    assert first.input_hash == second.input_hash == canonical_hash({"title": "t", "text_sha256": "x"})
    assert first.run_id != second.run_id


def test_none_result_is_recorded_as_failed(session):
    assert _run_metrics(_recorder(session), lambda: None) is None
    [run] = _runs(session)
    assert run.status == "failed"
    assert run.error_code == "no_result"


def test_custom_success_predicate(session):
    result = _run_metrics(_recorder(session), lambda: "failed", is_success=lambda r: r != "failed")
    assert result == "failed"
    assert _runs(session)[0].status == "failed"


def test_system_exit_is_recorded_then_reraised(session):
    def boom():
        raise SystemExit("Gemini APIの制限")

    with pytest.raises(SystemExit):
        _run_metrics(_recorder(session), boom)
    [run] = _runs(session)
    assert run.status == "failed"
    assert run.error_code == "SystemExit"


def test_run_persist_failure_raises_and_rolls_back():
    session = MagicMock()
    session.commit.side_effect = OperationalError("insert", {}, Exception("database is locked"))
    with pytest.raises(RunPersistError):
        _run_metrics(_recorder(session), lambda: {"data": {}})
    session.rollback.assert_called_once()


def test_decision_run_has_outcome_and_no_llm_fields(session):
    _recorder(session).record_decision(
        url=URL, stage="eligibility", outcome="withdrawn",
        outcome_reason="title_keyword:予想の取り下げ", input_payload={"title": "業績予想の取り下げ"},
    )
    [run] = _runs(session)
    assert run.run_kind == "route"
    assert run.stage == "eligibility"
    assert run.status == "succeeded"
    assert run.outcome == "withdrawn"
    assert run.outcome_reason == "title_keyword:予想の取り下げ"
    assert run.source_hash is None
    assert run.source_document_id is None
    assert run.input_locator == URL
    assert run.prompt_name is run.prompt_hash is run.model_name is run.model_provider is None


def test_source_failure_records_failed_run_and_returns_none(session):
    def resolver(*args, **kwargs):
        raise SourceVerificationError("download_failed", "404")

    recorder = _recorder(session, resolver=resolver)
    source = recorder.resolve_source(
        url=URL, disclosure_date="2026-02-19", time="15:30", pdf_root="/pdf", stage="stage1",
    )
    assert source is None
    [run] = _runs(session)
    assert run.status == "failed"
    assert run.stage == "stage1"
    assert run.error_code == "download_failed"
    assert run.source_hash is None
    assert run.input_locator == URL


def test_record_source_failure_after_verification_keeps_hash(session):
    _recorder(session).record_source_failure(url=URL, stage="metrics", error_code="pdf_read_failed", source=SOURCE)
    [run] = _runs(session)
    assert run.source_hash == SOURCE.source_hash
    assert run.input_locator == SOURCE.storage_uri
    assert run.error_code == "pdf_read_failed"


def test_run_llm_stage_without_recorder_calls_directly():
    assert run_llm_stage(None, None, stage="metrics", prompt_name="midterm_plan.md", input_payload={}, call=lambda: 42) == 42


def test_from_env_disabled_returns_none(session):
    assert ProvenanceRecorder.from_env(session, env={}) is None
    assert ProvenanceRecorder.from_env(session, env={"TDNET_PROVENANCE_ENABLED": "false"}) is None


def test_from_env_enabled_requires_migrated_tables():
    engine = create_engine("sqlite:///:memory:", future=True)
    with sessionmaker(bind=engine, future=True)() as empty:
        with pytest.raises(RuntimeError, match="migrate_tdnet_provenance_tables"):
            ProvenanceRecorder.from_env(empty, env={"TDNET_PROVENANCE_ENABLED": "true", "CODE_COMMIT": COMMIT})


def test_from_env_enabled_resolves_code_commit(session):
    recorder = ProvenanceRecorder.from_env(session, env={"TDNET_PROVENANCE_ENABLED": "true", "CODE_COMMIT": COMMIT})
    assert recorder.code_commit == COMMIT


def _spec(**overrides):
    values = dict(
        url=URL, source_document_id="doc", input_locator="loc", source_hash="a" * 64,
        input_hash="b" * 64, run_kind="extract", stage="metrics", code_commit=COMMIT,
        prompt_name="p.md", prompt_hash="c" * 64, model_provider="google",
        model_name="gemini", generation_config={"temperature": 0.0},
    )
    values.update(overrides)
    return RunSpec(**values)


def test_reuse_key_matches_ir_analytics_contract_algorithm():
    # ir_analytics_contract.processing.RunSpec.reuse_key() と同じ正規化
    spec = _spec()
    payload = {
        "source_hash": "a" * 64, "input_hash": "b" * 64, "run_kind": "extract", "stage": "metrics",
        "extractor_version": COMMIT, "prompt_hash": "c" * 64, "model_provider": "google",
        "model_name": "gemini", "generation_config": {"temperature": 0.0},
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert spec.reuse_key() == hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@pytest.mark.parametrize(
    "override",
    [{"prompt_hash": "d" * 64}, {"model_name": "other"}, {"source_hash": "e" * 64}, {"code_commit": "f" * 40}],
)
def test_reuse_key_changes_when_condition_changes(override):
    assert _spec().reuse_key() != _spec(**override).reuse_key()
