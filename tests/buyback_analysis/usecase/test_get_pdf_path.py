from unittest.mock import MagicMock, patch

import pytest
import requests

from buyback_analysis.usecase.get_pdf_path import fetch_pdf, get_pdf_path

URL = "https://www.release.tdnet.info/inbs/140120260218512345.pdf"


def _response(content=b"%PDF-1.4 body"):
    response = MagicMock()
    response.content = content
    return response


def test_fetch_pdf_downloads_into_publication_date_folder(tmp_path):
    with patch("buyback_analysis.usecase.get_pdf_path.requests.get", return_value=_response()) as get:
        path, fetched_at = fetch_pdf(URL, "20260219", str(tmp_path))

    get.assert_called_once_with(URL)
    assert path == str(tmp_path / "20260219" / "140120260218512345.pdf")
    assert open(path, "rb").read() == b"%PDF-1.4 body"
    assert fetched_at is not None and fetched_at.utcoffset() is not None
    # 一時ファイルが残らない
    assert [p.name for p in (tmp_path / "20260219").iterdir()] == ["140120260218512345.pdf"]


def test_fetch_pdf_reuses_existing_file_without_download(tmp_path):
    folder = tmp_path / "20260219"
    folder.mkdir()
    (folder / "140120260218512345.pdf").write_bytes(b"existing")

    with patch("buyback_analysis.usecase.get_pdf_path.requests.get") as get:
        path, fetched_at = fetch_pdf(URL, "20260219", str(tmp_path))

    get.assert_not_called()
    assert fetched_at is None
    assert open(path, "rb").read() == b"existing"


def test_fetch_pdf_returns_none_on_download_error(tmp_path):
    with patch(
        "buyback_analysis.usecase.get_pdf_path.requests.get",
        side_effect=requests.exceptions.ConnectionError("down"),
    ):
        assert fetch_pdf(URL, "20260219", str(tmp_path)) is None


def test_fetch_pdf_leaves_no_partial_file_when_write_fails(tmp_path):
    with patch("buyback_analysis.usecase.get_pdf_path.requests.get", return_value=_response()), patch(
        "buyback_analysis.usecase.get_pdf_path.os.replace", side_effect=OSError("disk full")
    ):
        with pytest.raises(OSError):
            fetch_pdf(URL, "20260219", str(tmp_path))
    assert list((tmp_path / "20260219").iterdir()) == []


def test_get_pdf_path_returns_path_only(tmp_path):
    with patch("buyback_analysis.usecase.get_pdf_path.requests.get", return_value=_response()):
        assert get_pdf_path(URL, "20260219", str(tmp_path)) == str(
            tmp_path / "20260219" / "140120260218512345.pdf"
        )
