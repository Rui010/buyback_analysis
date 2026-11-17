from types import SimpleNamespace
from unittest.mock import MagicMock

from buyback_analysis.usecase.process_buyback_event_document import (
    process_buyback_event_document,
)


def test_process_runs_stage_and_saves_with_current_document_runs(monkeypatch):
    recorder = MagicMock(document_run_ids=["run-1"])
    source = SimpleNamespace(source_hash="hash")
    stage_result = SimpleNamespace(
        extraction=SimpleNamespace(events=["event"]),
        quote_verified_flags=(True,),
    )
    run_stage = MagicMock(return_value=stage_result)
    save = MagicMock(return_value=True)
    monkeypatch.setattr(
        "buyback_analysis.usecase.process_buyback_event_document.run_buyback_event_stage",
        run_stage,
    )
    monkeypatch.setattr(
        "buyback_analysis.usecase.process_buyback_event_document.save_buyback_event_result",
        save,
    )

    result = process_buyback_event_document(
        MagicMock(),
        recorder,
        source,
        title="title",
        content="content",
        code="1234",
        name="name",
        url="https://example.test/a.pdf",
        disclosure_datetime="2026-11-17T15:00:00",
    )

    assert result is True
    run_stage.assert_called_once()
    assert save.call_args.kwargs["run_ids"] == ["run-1"]


def test_process_does_not_save_when_stage_fails(monkeypatch):
    recorder = MagicMock()
    monkeypatch.setattr(
        "buyback_analysis.usecase.process_buyback_event_document.run_buyback_event_stage",
        MagicMock(return_value=None),
    )
    save = MagicMock()
    monkeypatch.setattr(
        "buyback_analysis.usecase.process_buyback_event_document.save_buyback_event_result",
        save,
    )

    result = process_buyback_event_document(
        MagicMock(), recorder, None, title="title", content="content", code="1234",
        name="name", url="https://example.test/a.pdf", disclosure_datetime=None,
    )

    assert result is False
    save.assert_not_called()
