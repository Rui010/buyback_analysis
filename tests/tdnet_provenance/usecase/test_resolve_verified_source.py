import datetime
import hashlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tdnet_provenance.models.base import ProvenanceBase
from tdnet_provenance.models.tdnet_source_document import TdnetSourceDocument
from tdnet_provenance.usecase.resolve_verified_source import (
    SourceVerificationError,
    resolve_verified_source,
)

URL = "https://www.release.tdnet.info/inbs/140120260218512345.pdf"
DOC_ID = "140120260218512345"
PDF_BYTES = b"%PDF-1.4 original"
FETCHED_AT = datetime.datetime(2026, 2, 19, 7, 0, tzinfo=datetime.timezone.utc)
NOW = datetime.datetime(2026, 2, 19, 8, 0, tzinfo=datetime.timezone.utc)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    ProvenanceBase.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True)() as s:
        yield s


class FakeFetch:
    """get_pdf_path.fetch_pdf の代役。呼び出し回数を記録する。"""

    def __init__(self, content=PDF_BYTES, fetched_at=FETCHED_AT, fail=False):
        self.content = content
        self.fetched_at = fetched_at
        self.fail = fail
        self.calls = []

    def __call__(self, url, pud_date_str, save_dir):
        self.calls.append((url, pud_date_str, save_dir))
        if self.fail:
            return None
        path = f"{save_dir}/{pud_date_str}/{DOC_ID}.pdf"
        import os

        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(self.content)
            return path, self.fetched_at
        return path, None


def _resolve(session, tmp_path, fetch, date="2026-02-19", time="15:30"):
    return resolve_verified_source(
        session, url=URL, disclosure_date=date, time=time,
        pdf_root=tmp_path, fetch=fetch, now=lambda: NOW,
    )


def test_first_fetch_registers_ledger_and_returns_verified_path(session, tmp_path):
    fetch = FakeFetch()
    source = _resolve(session, tmp_path, fetch)

    expected_hash = hashlib.sha256(PDF_BYTES).hexdigest()
    assert source.source_hash == expected_hash
    assert source.storage_uri == f"tdnet-pdf://20260219/{DOC_ID}.pdf"
    assert source.path == (tmp_path / "20260219" / f"{DOC_ID}.pdf").resolve()
    assert source.path.read_bytes() == PDF_BYTES

    entry = session.get(TdnetSourceDocument, URL)
    assert entry.source_hash == expected_hash
    assert entry.external_document_id == DOC_ID
    assert entry.disclosure_date == "2026-02-19"
    assert entry.published_at == "2026-02-19T15:30:00+09:00"
    assert entry.file_size == len(PDF_BYTES)
    assert entry.fetched_at == FETCHED_AT.isoformat()
    assert entry.observed_at == NOW.isoformat()


def test_existing_file_without_ledger_is_registered_without_fetched_at(session, tmp_path):
    folder = tmp_path / "20260219"
    folder.mkdir()
    (folder / f"{DOC_ID}.pdf").write_bytes(PDF_BYTES)

    _resolve(session, tmp_path, FakeFetch())

    entry = session.get(TdnetSourceDocument, URL)
    assert entry.fetched_at is None
    assert entry.observed_at == NOW.isoformat()


def test_registered_source_is_rehashed_without_refetch(session, tmp_path):
    _resolve(session, tmp_path, FakeFetch())
    second_fetch = FakeFetch()

    source = _resolve(session, tmp_path, second_fetch)

    assert second_fetch.calls == []
    assert source.source_hash == hashlib.sha256(PDF_BYTES).hexdigest()


def test_replaced_pdf_is_rejected_as_source_conflict(session, tmp_path):
    first = _resolve(session, tmp_path, FakeFetch())
    first.path.write_bytes(b"%PDF-1.4 replaced")

    with pytest.raises(SourceVerificationError) as exc:
        _resolve(session, tmp_path, FakeFetch())
    assert exc.value.error_code == "source_conflict"
    # 台帳は書き換えない
    assert session.get(TdnetSourceDocument, URL).source_hash == first.source_hash


def test_missing_registered_pdf_stops_without_refetch(session, tmp_path):
    first = _resolve(session, tmp_path, FakeFetch())
    first.path.unlink()
    fetch = FakeFetch()

    with pytest.raises(SourceVerificationError) as exc:
        _resolve(session, tmp_path, fetch)
    assert exc.value.error_code == "source_missing"
    assert fetch.calls == []


def test_restored_pdf_with_same_hash_resumes(session, tmp_path):
    first = _resolve(session, tmp_path, FakeFetch())
    first.path.unlink()
    first.path.write_bytes(PDF_BYTES)

    assert _resolve(session, tmp_path, FakeFetch()).source_hash == first.source_hash


def test_download_failure_raises_without_registering(session, tmp_path):
    with pytest.raises(SourceVerificationError) as exc:
        _resolve(session, tmp_path, FakeFetch(fail=True))
    assert exc.value.error_code == "download_failed"
    assert session.get(TdnetSourceDocument, URL) is None


def test_invalid_url_is_contract_error(session, tmp_path):
    with pytest.raises(SourceVerificationError) as exc:
        resolve_verified_source(
            session, url="https://example.com/a.html", disclosure_date="2026-02-19",
            time=None, pdf_root=tmp_path, fetch=FakeFetch(), now=lambda: NOW,
        )
    assert exc.value.error_code == "contract_error"


def test_ledger_disclosure_date_mismatch_is_contract_error(session, tmp_path):
    _resolve(session, tmp_path, FakeFetch())
    with pytest.raises(SourceVerificationError) as exc:
        _resolve(session, tmp_path, FakeFetch(), date="2026-02-20")
    assert exc.value.error_code == "contract_error"


def test_fetched_path_outside_storage_uri_is_contract_error(session, tmp_path):
    def wrong_place(url, pud_date_str, save_dir):
        path = tmp_path / "elsewhere.pdf"
        path.write_bytes(PDF_BYTES)
        return str(path), None

    with pytest.raises(SourceVerificationError) as exc:
        _resolve(session, tmp_path, wrong_place)
    assert exc.value.error_code == "contract_error"
    assert session.get(TdnetSourceDocument, URL) is None


def test_concurrent_registration_uses_existing_ledger_row(tmp_path):
    # 別パイプラインが同じURLを先に登録した場合、その行を基準値として照合する
    engine = create_engine(f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}", future=True)
    ProvenanceBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    pdf_root = tmp_path / "pdf"
    inner_fetch = FakeFetch()

    def racing_fetch(url, pud_date_str, save_dir):
        fetched = inner_fetch(url, pud_date_str, save_dir)
        with Session() as other:
            resolve_verified_source(
                other, url=URL, disclosure_date="2026-02-19", time="15:30",
                pdf_root=pdf_root, fetch=FakeFetch(), now=lambda: FETCHED_AT,
            )
        return fetched

    with Session() as session:
        source = resolve_verified_source(
            session, url=URL, disclosure_date="2026-02-19", time="15:30",
            pdf_root=pdf_root, fetch=racing_fetch, now=lambda: NOW,
        )
        assert source.source_hash == hashlib.sha256(PDF_BYTES).hexdigest()
        # 先に登録された行が残る
        assert session.get(TdnetSourceDocument, URL).observed_at == FETCHED_AT.isoformat()


def test_hash_failure_on_first_registration(session, tmp_path, monkeypatch):
    import tdnet_provenance.usecase.resolve_verified_source as module

    def broken(path):
        raise OSError("read error")

    monkeypatch.setattr(module, "sha256_file", broken)
    with pytest.raises(SourceVerificationError) as exc:
        _resolve(session, tmp_path, FakeFetch())
    assert exc.value.error_code == "hash_failed"
    assert session.get(TdnetSourceDocument, URL) is None


def test_hash_failure_on_verification(session, tmp_path, monkeypatch):
    import tdnet_provenance.usecase.resolve_verified_source as module

    _resolve(session, tmp_path, FakeFetch())

    def broken(path):
        raise OSError("read error")

    monkeypatch.setattr(module, "sha256_file", broken)
    with pytest.raises(SourceVerificationError) as exc:
        _resolve(session, tmp_path, FakeFetch())
    assert exc.value.error_code == "hash_failed"
