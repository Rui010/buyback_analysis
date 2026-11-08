from unittest.mock import patch

import pytest

from midterm_plan_analysis.usecase.run_midterm_stages import (
    run_midterm_classification,
    run_midterm_keywords,
    run_midterm_metrics,
)
from tdnet_provenance.usecase.prepare_pdf_input import PdfInput

MODULE = "midterm_plan_analysis.usecase.run_midterm_stages"
DOC = dict(title="中期経営計画", code="1234", name="A社")


def _native(source):
    return PdfInput(source=source, pdf_path=str(source.path), content=None)


def _text(source):
    return PdfInput(source=source, pdf_path=None, content="本文")


def test_metrics_native_passes_verified_pdf(make_recorder, verified_pdf, runs):
    with patch(f"{MODULE}.parse_pdf_by_llm", return_value={"data": {}}) as native, patch(
        f"{MODULE}.parse_text_by_llm"
    ) as text:
        assert run_midterm_metrics(make_recorder(verified_pdf), _native(verified_pdf), **DOC) == {"data": {}}

    native.assert_called_once_with(pdf_path=str(verified_pdf.path), prompt_filename="midterm_plan_native.md", **DOC)
    text.assert_not_called()
    assert runs() == [("metrics", "extract", "succeeded", None, None)]


def test_metrics_text_passes_verified_text(make_recorder, verified_pdf, runs):
    with patch(f"{MODULE}.parse_text_by_llm", return_value=None) as text:
        assert run_midterm_metrics(make_recorder(verified_pdf), _text(verified_pdf), **DOC) is None

    text.assert_called_once_with(content="本文", prompt_filename="midterm_plan.md", **DOC)
    assert runs() == [("metrics", "extract", "failed", "no_result", None)]


@pytest.mark.parametrize("native", [True, False])
def test_keywords_uses_same_input_as_metrics(make_recorder, verified_pdf, runs, native):
    pdf_input = _native(verified_pdf) if native else _text(verified_pdf)
    with patch(f"{MODULE}.extract_midterm_keywords_native", return_value={"data": {}}) as kw_native, patch(
        f"{MODULE}.extract_midterm_keywords", return_value={"data": {}}
    ) as kw_text:
        run_midterm_keywords(make_recorder(verified_pdf), pdf_input, **DOC)

    if native:
        kw_native.assert_called_once_with(pdf_path=str(verified_pdf.path), **DOC)
        kw_text.assert_not_called()
    else:
        kw_text.assert_called_once_with(content="本文", **DOC)
        kw_native.assert_not_called()
    assert runs() == [("keywords", "extract", "succeeded", None, None)]


@pytest.mark.parametrize("status,expected", [("no_targets", "succeeded"), ("failed", "failed")])
def test_classification_status_maps_to_run_status(make_recorder, verified_pdf, runs, status, expected):
    with patch(f"{MODULE}.classify_midterm_by_llm", return_value=status) as classify:
        assert run_midterm_classification(make_recorder(verified_pdf), _text(verified_pdf), **DOC) == status

    classify.assert_called_once_with(content="本文", **DOC)
    assert runs()[0][:3] == ("classification", "extract", expected)


def test_classification_native_keeps_empty_content(make_recorder, verified_pdf):
    # 従来どおりnative方式では分類に空文字を渡す
    with patch(f"{MODULE}.classify_midterm_by_llm", return_value="no_targets") as classify:
        run_midterm_classification(make_recorder(verified_pdf), _native(verified_pdf), **DOC)
    classify.assert_called_once_with(content="", **DOC)


def test_disabled_calls_llm_without_recording(provenance_session, runs):
    with patch(f"{MODULE}.parse_text_by_llm", return_value={"data": {}}) as text:
        run_midterm_metrics(None, PdfInput(source=None, pdf_path=None, content="本文"), **DOC)
    text.assert_called_once()
    assert runs() == []


@pytest.mark.parametrize("native", [True, False])
def test_metrics_run_records_module_version_and_config(make_recorder, verified_pdf, provenance_session, native):
    import json

    from buyback_analysis.usecase import parse_pdf_by_llm as pdf_module
    from buyback_analysis.usecase import parse_text_by_llm as text_module
    from tdnet_provenance.models.processing_run import ProcessingRun

    module = pdf_module if native else text_module
    pdf_input = _native(verified_pdf) if native else _text(verified_pdf)
    with patch(f"{MODULE}.parse_pdf_by_llm", return_value={"data": {}}), patch(
        f"{MODULE}.parse_text_by_llm", return_value={"data": {}}
    ):
        run_midterm_metrics(make_recorder(verified_pdf), pdf_input, **DOC)

    run = provenance_session.query(ProcessingRun).one()
    assert run.extractor_version == module.EXTRACTOR_VERSION
    assert json.loads(run.generation_config) == module.GENERATION_CONFIG
