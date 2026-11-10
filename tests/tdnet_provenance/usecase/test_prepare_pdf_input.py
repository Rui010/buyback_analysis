from unittest.mock import patch

import pytest

from tdnet_provenance.usecase.prepare_pdf_input import PdfInput, prepare_pdf_input

URL = "https://www.release.tdnet.info/inbs/140120260218512345.pdf"

MODULE = "tdnet_provenance.usecase.prepare_pdf_input"


def _prepare(recorder, use_native, **overrides):
    kwargs = dict(
        url=URL, disclosure_date="2026-02-19", time="15:30", pud_date_str="20260219",
        pdf_root="/pdf", use_native=use_native, stage="metrics",
    )
    kwargs.update(overrides)
    return prepare_pdf_input(recorder, **kwargs)


def test_native_uses_verified_path(make_recorder, verified_pdf, runs):
    with patch(f"{MODULE}.get_pdf_path") as legacy_path, patch(f"{MODULE}.get_pdf_data") as legacy_data:
        result = _prepare(make_recorder(verified_pdf), use_native=True)

    assert result == PdfInput(source=verified_pdf, pdf_path=str(verified_pdf.path), content=None)
    legacy_path.assert_not_called()
    legacy_data.assert_not_called()
    assert runs() == []  # 照合成功だけではrunを作らない


def test_text_reads_verified_path(make_recorder, verified_pdf):
    with patch(f"{MODULE}.extract_pdf_text", return_value="本文") as extract, patch(
        f"{MODULE}.get_pdf_data"
    ) as legacy_data:
        result = _prepare(make_recorder(verified_pdf), use_native=False)

    extract.assert_called_once_with(str(verified_pdf.path))
    legacy_data.assert_not_called()
    assert result == PdfInput(source=verified_pdf, pdf_path=None, content="本文")


@pytest.mark.parametrize("use_native", [True, False])
def test_source_failure_returns_none_with_failed_run(make_recorder, runs, use_native):
    with patch(f"{MODULE}.extract_pdf_text") as extract, patch(f"{MODULE}.get_pdf_path") as legacy_path:
        assert _prepare(make_recorder(error_code="source_conflict"), use_native=use_native) is None

    extract.assert_not_called()
    legacy_path.assert_not_called()  # 照合に失敗しても従来経路で取り直さない
    assert runs() == [("metrics", "extract", "failed", "source_conflict", None)]


def test_text_read_failure_records_failed_run(make_recorder, verified_pdf, runs):
    with patch(f"{MODULE}.extract_pdf_text", return_value=None):
        assert _prepare(make_recorder(verified_pdf), use_native=False, stage="keywords") is None
    assert runs() == [("keywords", "extract", "failed", "pdf_read_failed", None)]


def test_disabled_native_uses_legacy_path():
    with patch(f"{MODULE}.get_pdf_path", return_value="/pdf/20260219/a.pdf") as legacy:
        result = _prepare(None, use_native=True, pud_date_str="20260218")

    legacy.assert_called_once_with(url=URL, pud_date_str="20260218", save_dir="/pdf")
    assert result == PdfInput(source=None, pdf_path="/pdf/20260219/a.pdf", content=None)


def test_disabled_text_uses_legacy_data():
    with patch(f"{MODULE}.get_pdf_data", return_value="本文") as legacy:
        result = _prepare(None, use_native=False)

    legacy.assert_called_once_with(url=URL, pud_date_str="20260219", save_dir="/pdf")
    assert result == PdfInput(source=None, pdf_path=None, content="本文")


@pytest.mark.parametrize("use_native,target", [(True, "get_pdf_path"), (False, "get_pdf_data")])
def test_disabled_fetch_failure_returns_none(use_native, target):
    with patch(f"{MODULE}.{target}", return_value=None):
        assert _prepare(None, use_native=use_native) is None


def test_text_with_page_markers_reads_pages_once(make_recorder, verified_pdf):
    with patch(f"{MODULE}.extract_pdf_pages", return_value=["a", "b"]) as pages, patch(
        f"{MODULE}.extract_pdf_text"
    ) as plain:
        result = _prepare(make_recorder(verified_pdf), use_native=False, page_markers=True)

    pages.assert_called_once_with(str(verified_pdf.path))
    plain.assert_not_called()
    # contentは従来どおり区切りなし（keywords・classification用）、paged_contentだけに目印を入れる
    assert result == PdfInput(
        source=verified_pdf, pdf_path=None, content="ab",
        paged_content="--- page 1 ---\na\n--- page 2 ---\nb",
    )


def test_text_with_page_markers_read_failure_records_failed_run(make_recorder, verified_pdf, runs):
    with patch(f"{MODULE}.extract_pdf_pages", return_value=None):
        assert _prepare(make_recorder(verified_pdf), use_native=False, page_markers=True) is None
    assert runs() == [("metrics", "extract", "failed", "pdf_read_failed", None)]


def test_native_ignores_page_markers(make_recorder, verified_pdf):
    with patch(f"{MODULE}.extract_pdf_pages") as pages:
        result = _prepare(make_recorder(verified_pdf), use_native=True, page_markers=True)
    pages.assert_not_called()
    assert result.paged_content is None


def test_disabled_text_with_page_markers_reads_fetched_pdf():
    with patch(f"{MODULE}.get_pdf_path", return_value="/pdf/20260219/a.pdf") as legacy, patch(
        f"{MODULE}.extract_pdf_pages", return_value=["a"]
    ) as pages:
        result = _prepare(None, use_native=False, page_markers=True)

    legacy.assert_called_once_with(url=URL, pud_date_str="20260219", save_dir="/pdf")
    pages.assert_called_once_with("/pdf/20260219/a.pdf")
    assert result == PdfInput(source=None, pdf_path=None, content="a", paged_content="--- page 1 ---\na")


@pytest.mark.parametrize("path,pages", [(None, ["a"]), ("/pdf/a.pdf", None)])
def test_disabled_text_with_page_markers_failure_returns_none(path, pages):
    with patch(f"{MODULE}.get_pdf_path", return_value=path), patch(f"{MODULE}.extract_pdf_pages", return_value=pages):
        assert _prepare(None, use_native=False, page_markers=True) is None
