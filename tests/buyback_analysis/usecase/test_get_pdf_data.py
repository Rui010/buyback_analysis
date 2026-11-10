from unittest.mock import MagicMock, patch

from buyback_analysis.usecase.get_pdf_data import (
    extract_pdf_pages,
    extract_pdf_text,
    format_pages_with_markers,
    get_pdf_data,
)


def _reader(texts, encrypted=False):
    reader = MagicMock()
    reader.is_encrypted = encrypted
    reader.pages = [MagicMock(extract_text=MagicMock(return_value=t)) for t in texts]
    return reader


def test_extract_pdf_text_reads_given_path(tmp_path):
    path = tmp_path / "a.pdf"
    path.write_bytes(b"%PDF")
    with patch("buyback_analysis.usecase.get_pdf_data.PdfReader", return_value=_reader(["a", "b"])):
        assert extract_pdf_text(str(path)) == "ab"


def test_extract_pdf_text_returns_none_on_read_error(tmp_path):
    assert extract_pdf_text(str(tmp_path / "missing.pdf")) is None


def test_get_pdf_data_extracts_from_fetched_path(tmp_path):
    path = tmp_path / "a.pdf"
    path.write_bytes(b"%PDF")
    with patch("buyback_analysis.usecase.get_pdf_data.get_pdf_path", return_value=str(path)), patch(
        "buyback_analysis.usecase.get_pdf_data.PdfReader", return_value=_reader(["x"])
    ):
        assert get_pdf_data("https://x/a.pdf", "20260219", str(tmp_path)) == "x"


def test_get_pdf_data_returns_none_when_fetch_fails():
    with patch("buyback_analysis.usecase.get_pdf_data.get_pdf_path", return_value=None):
        assert get_pdf_data("https://x/a.pdf", "20260219") is None


def test_extract_pdf_pages_returns_text_per_page(tmp_path):
    path = tmp_path / "a.pdf"
    path.write_bytes(b"%PDF")
    with patch("buyback_analysis.usecase.get_pdf_data.PdfReader", return_value=_reader(["a", "b"])):
        assert extract_pdf_pages(str(path)) == ["a", "b"]


def test_extract_pdf_pages_returns_none_on_read_error(tmp_path):
    assert extract_pdf_pages(str(tmp_path / "missing.pdf")) is None


def test_format_pages_with_markers_numbers_pages_from_one():
    assert format_pages_with_markers(["a", "b"]) == "--- page 1 ---\na\n--- page 2 ---\nb"


def test_format_pages_with_markers_keeps_empty_pages():
    assert format_pages_with_markers(["", "b"]) == "--- page 1 ---\n\n--- page 2 ---\nb"
