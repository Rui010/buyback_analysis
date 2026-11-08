from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from forecast_revision_analysis.usecase.run_forecast_revision_stages import (
    find_withdrawn_keyword,
    record_withdrawn_route,
    run_stage1_and_stage2,
)
from tdnet_provenance.models.processing_run import ProcessingRun
from tdnet_provenance.usecase.prepare_pdf_input import PdfInput
from tdnet_provenance.usecase.provenance_recorder import ProvenanceRecorder, RunPersistError

MODULE = "forecast_revision_analysis.usecase.run_forecast_revision_stages"
DOC = dict(title="業績予想の修正", code="1234", name="A社")
URL = "https://www.release.tdnet.info/inbs/140120260218512345.pdf"
STAGE1 = {"data": {"periods": [{"prev_value": 1, "curr_value": 2}]}}


def _patches(stage1=STAGE1, stage2=None):
    return (
        patch(f"{MODULE}.extract_forecast_revision_stage1_native", return_value=stage1),
        patch(f"{MODULE}.extract_forecast_revision_stage1", return_value=stage1),
        patch(f"{MODULE}.infer_forecast_revision_stage2", return_value=stage2),
        patch(f"{MODULE}.build_stage2_context", return_value="context"),
    )


def test_native_stage1_gets_verified_pdf_and_stage2_failure_is_separate_run(make_recorder, verified_pdf, runs):
    p_native, p_text, p_stage2, p_ctx = _patches(stage2=None)
    with p_native as native, p_text as text, p_stage2 as stage2, p_ctx:
        merged = run_stage1_and_stage2(
            make_recorder(verified_pdf), PdfInput(verified_pdf, str(verified_pdf.path), None), **DOC
        )

    native.assert_called_once_with(pdf_path=str(verified_pdf.path), **DOC)
    text.assert_not_called()
    stage2.assert_called_once_with("context")
    assert merged["data"]["periods"] == STAGE1["data"]["periods"]  # Stage2失敗でもStage1は残る
    assert runs() == [
        ("stage1", "extract", "succeeded", None, None),
        ("stage2", "extract", "failed", "no_result", None),
    ]


def test_text_stage1_gets_verified_text(make_recorder, verified_pdf, runs):
    p_native, p_text, p_stage2, p_ctx = _patches(stage2={"data": {}})
    with p_native as native, p_text as text, p_stage2, p_ctx:
        run_stage1_and_stage2(make_recorder(verified_pdf), PdfInput(verified_pdf, None, "本文"), **DOC)

    text.assert_called_once_with(content="本文", **DOC)
    native.assert_not_called()
    assert [r[:3] for r in runs()] == [("stage1", "extract", "succeeded"), ("stage2", "extract", "succeeded")]


def test_stage1_failure_skips_stage2(make_recorder, verified_pdf, runs):
    p_native, p_text, p_stage2, p_ctx = _patches(stage1=None)
    with p_native, p_text, p_stage2 as stage2, p_ctx:
        assert run_stage1_and_stage2(make_recorder(verified_pdf), PdfInput(verified_pdf, None, "本文"), **DOC) is None
    stage2.assert_not_called()
    assert runs() == [("stage1", "extract", "failed", "no_result", None)]


def test_run_persist_failure_stops_before_result_is_returned(verified_pdf):
    # runを保存できなければ例外で止まり、呼び出し側は抽出結果を保存しない
    session = MagicMock()
    session.commit.side_effect = OperationalError("insert", {}, Exception("database is locked"))
    recorder = ProvenanceRecorder(session, code_commit="0" * 40)
    p_native, p_text, p_stage2, p_ctx = _patches()
    with p_native, p_text, p_stage2 as stage2, p_ctx:
        with pytest.raises(RunPersistError):
            run_stage1_and_stage2(recorder, PdfInput(verified_pdf, None, "本文"), **DOC)
    stage2.assert_not_called()


def test_disabled_runs_stages_without_recording(runs):
    p_native, p_text, p_stage2, p_ctx = _patches(stage2={"data": {}})
    with p_native, p_text as text, p_stage2, p_ctx:
        run_stage1_and_stage2(None, PdfInput(None, None, "本文"), **DOC)
    text.assert_called_once()
    assert runs() == []


@pytest.mark.parametrize(
    "title,expected",
    [
        ("業績予想の取り下げに関するお知らせ", "予想の取り下げ"),
        ("業績予想の修正及び中期経営計画の取り下げ", None),
        ("通期業績予想を撤回", "予想を撤回"),
    ],
)
def test_find_withdrawn_keyword(title, expected):
    assert find_withdrawn_keyword(title) == expected


def test_withdrawn_route_records_only_eligibility_run(make_recorder, runs, provenance_session):
    assert record_withdrawn_route(make_recorder(), url=URL, title="業績予想の取り下げ") is True

    assert runs() == [("eligibility", "route", "succeeded", None, "withdrawn")]
    run = provenance_session.query(ProcessingRun).one()
    assert run.outcome_reason == "title_keyword:予想の取り下げ"
    assert run.source_hash is None and run.prompt_name is None


def test_not_withdrawn_records_nothing(make_recorder, runs):
    assert record_withdrawn_route(make_recorder(), url=URL, title="業績予想の修正") is False
    assert runs() == []


def test_withdrawn_route_without_recorder(runs):
    assert record_withdrawn_route(None, url=URL, title="業績予想の取り下げ") is True
    assert runs() == []
