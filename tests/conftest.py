"""processing run記録を検証するテスト共通のfixture（インメモリSQLite上の実ProvenanceRecorder）。"""

import datetime
import hashlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tdnet_provenance.models.base import ProvenanceBase
from tdnet_provenance.models.processing_run import ProcessingRun
from tdnet_provenance.usecase.provenance_recorder import ProvenanceRecorder
from tdnet_provenance.usecase.resolve_verified_source import (
    SourceVerificationError,
    VerifiedSource,
)

COMMIT = "0123456789abcdef0123456789abcdef01234567"
URL = "https://www.release.tdnet.info/inbs/140120260218512345.pdf"
NOW = datetime.datetime(2026, 2, 19, 8, 0, tzinfo=datetime.timezone.utc)


@pytest.fixture
def provenance_session():
    engine = create_engine("sqlite:///:memory:", future=True)
    ProvenanceBase.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True)() as s:
        yield s


@pytest.fixture
def verified_pdf(tmp_path) -> VerifiedSource:
    """照合済みとして扱う実ファイル付きのVerifiedSource。"""
    path = tmp_path / "pdf" / "20260219" / "140120260218512345.pdf"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"%PDF-1.4 verified")
    return VerifiedSource(
        url=URL,
        source_document_id="doc-uuid",
        external_document_id="140120260218512345",
        storage_uri="tdnet-pdf://20260219/140120260218512345.pdf",
        source_hash=hashlib.sha256(b"%PDF-1.4 verified").hexdigest(),
        path=path.resolve(),
    )


@pytest.fixture
def make_recorder(provenance_session):
    def factory(source: VerifiedSource | None = None, error_code: str | None = None):
        def resolver(session, **kwargs):
            if error_code:
                raise SourceVerificationError(error_code, "test")
            return source

        return ProvenanceRecorder(provenance_session, code_commit=COMMIT, clock=lambda: NOW, resolver=resolver)

    return factory


@pytest.fixture
def runs(provenance_session):
    def fetch():
        return [
            (r.stage, r.run_kind, r.status, r.error_code, r.outcome)
            for r in provenance_session.query(ProcessingRun).order_by(ProcessingRun.started_at).all()
        ]

    return fetch
