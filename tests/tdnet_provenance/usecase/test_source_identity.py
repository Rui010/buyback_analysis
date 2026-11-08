import datetime
import hashlib
from pathlib import Path
from uuid import UUID

import pandas as pd
import pytest

from tdnet_provenance.usecase.source_identity import (
    SourceContractError,
    build_published_at,
    build_storage_uri,
    disclosure_date_iso,
    disclosure_folder,
    external_document_id,
    resolve_storage_path,
    sha256_file,
    source_document_id,
)

URL = "https://www.release.tdnet.info/inbs/140120260218512345.pdf"


def test_external_document_id_strips_pdf_suffix():
    assert external_document_id(URL) == "140120260218512345"


@pytest.mark.parametrize("url", ["", "https://example.com/inbs/", "https://example.com/a.html", "https://example.com/.pdf"])
def test_external_document_id_rejects_invalid_urls(url):
    with pytest.raises(SourceContractError):
        external_document_id(url)


@pytest.mark.parametrize(
    "value",
    [
        datetime.date(2026, 2, 19),
        datetime.datetime(2026, 2, 19, 0, 0),
        pd.Timestamp("2026-02-19"),
        "2026-02-19",
        "2026/02/19",
    ],
)
def test_disclosure_folder_uses_publication_date(value):
    assert disclosure_folder(value) == "20260219"
    assert disclosure_date_iso(value) == "2026-02-19"


def test_disclosure_folder_rejects_invalid_date():
    with pytest.raises(SourceContractError):
        disclosure_folder("not-a-date")


def test_storage_uri_uses_publication_date_not_document_id_date():
    # 文書IDは20260218を含むが、公表日2026-02-19のフォルダを使う
    document_id = external_document_id(URL)
    uri = build_storage_uri(disclosure_folder("2026-02-19"), document_id)
    assert uri == "tdnet-pdf://20260219/140120260218512345.pdf"


def test_resolve_storage_path(tmp_path):
    path = resolve_storage_path(tmp_path, "tdnet-pdf://20260219/abc.pdf", "abc")
    assert path == (tmp_path / "20260219" / "abc.pdf").resolve()


@pytest.mark.parametrize(
    "uri,document_id",
    [
        ("file://20260219/abc.pdf", "abc"),
        ("tdnet-pdf://20260219/other.pdf", "abc"),
        ("tdnet-pdf://../abc.pdf", "abc"),
    ],
)
def test_resolve_storage_path_rejects_mismatch(tmp_path, uri, document_id):
    with pytest.raises(SourceContractError):
        resolve_storage_path(tmp_path / "root", uri, document_id)


def test_sha256_file_matches_known_bytes(tmp_path):
    content = b"%PDF-1.4 known bytes"
    path = Path(tmp_path) / "a.pdf"
    path.write_bytes(content)
    assert sha256_file(path) == hashlib.sha256(content).hexdigest()


def test_build_published_at_uses_jst_offset():
    assert build_published_at("2026-02-19", "15:30") == "2026-02-19T15:30:00+09:00"


@pytest.mark.parametrize("time_value", [None, "", "25:00", "abc"])
def test_build_published_at_returns_none_for_unknown_time(time_value):
    assert build_published_at("2026-02-19", time_value) is None


def test_source_document_id_matches_ir_analytics_contract():
    # ir_analytics_contract.tdnet.source_document_id と同じ uuid5(TDNET_NAMESPACE, "tdnet:<id>")
    from uuid import uuid5

    namespace = UUID("d86f2629-2188-4ef6-90db-aeddb5f79b45")
    assert source_document_id("abc") == str(uuid5(namespace, "tdnet:abc"))
