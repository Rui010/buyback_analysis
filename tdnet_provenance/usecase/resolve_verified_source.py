"""運用原典台帳への初回登録と、抽出run開始前の再hash照合（tdnet-provenance-v1 §4.1）。"""

import datetime
import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.exc import IntegrityError

from buyback_analysis.usecase.get_pdf_path import fetch_pdf
from tdnet_provenance.models.tdnet_source_document import TdnetSourceDocument
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


class SourceVerificationError(Exception):
    """原典を確定できない。error_codeはfailed runのerror_codeにそのまま記録する。

    contract_error / download_failed / hash_failed / source_missing / source_conflict
    """

    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True)
class VerifiedSource:
    url: str
    source_document_id: str
    external_document_id: str
    storage_uri: str
    source_hash: str
    path: Path  # 再hash済みでLLM入力に使う唯一のパス。runのmetadataやinput_hashには含めない


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _register(session, *, url, document_id, disclosure_date, time, pdf_root, fetch, now) -> TdnetSourceDocument:
    folder = disclosure_folder(disclosure_date)
    storage_uri = build_storage_uri(folder, document_id)
    fetched = fetch(url, folder, str(pdf_root))
    if fetched is None:
        raise SourceVerificationError("download_failed", f"PDFを取得できません: {url}")
    path, fetched_at = fetched
    if Path(path).resolve() != resolve_storage_path(pdf_root, storage_uri, document_id):
        raise SourceVerificationError("contract_error", f"保存先がstorage_uriと一致しません: {path}")
    try:
        source_hash = sha256_file(path)
        file_size = os.path.getsize(path)
    except OSError as exc:
        raise SourceVerificationError("hash_failed", f"PDFをhashできません: {path}") from exc

    entry = TdnetSourceDocument(
        url=url,
        source_document_id=source_document_id(document_id),
        external_document_id=document_id,
        disclosure_date=disclosure_date_iso(disclosure_date),
        published_at=build_published_at(disclosure_date, time),
        storage_uri=storage_uri,
        source_hash=source_hash,
        file_size=file_size,
        fetched_at=fetched_at.isoformat() if fetched_at else None,
        observed_at=now().isoformat(),
    )
    session.add(entry)
    try:
        session.commit()
    except IntegrityError:
        # 別パイプラインが同じURLを先に登録した場合は、その行を基準値として使う
        session.rollback()
        entry = session.get(TdnetSourceDocument, url)
        if entry is None:
            raise
    except Exception:
        session.rollback()
        raise
    return entry


def _verify(entry: TdnetSourceDocument, pdf_root) -> VerifiedSource:
    path = resolve_storage_path(pdf_root, entry.storage_uri, entry.external_document_id)
    if not path.is_file():
        raise SourceVerificationError("source_missing", f"台帳登録済みのPDFがありません: {path}")
    try:
        actual_hash = sha256_file(path)
    except OSError as exc:
        raise SourceVerificationError("hash_failed", f"PDFをhashできません: {path}") from exc
    if actual_hash != entry.source_hash:
        raise SourceVerificationError("source_conflict", f"PDFのhashが台帳と一致しません: {path}")
    return VerifiedSource(
        url=entry.url,
        source_document_id=entry.source_document_id,
        external_document_id=entry.external_document_id,
        storage_uri=entry.storage_uri,
        source_hash=entry.source_hash,
        path=path,
    )


def resolve_verified_source(
    session, *, url: str, disclosure_date, time, pdf_root, fetch=fetch_pdf, now=_utc_now
) -> VerifiedSource:
    """台帳行を読み（なければ初回登録し）、実ファイルを再hashして照合済みの原典を返す。

    台帳登録済みのURLは再ダウンロードしない。PDFが消えていれば source_missing、
    hashが変わっていれば source_conflict で停止し、台帳は書き換えない。
    """
    try:
        document_id = external_document_id(url)
        date_iso = disclosure_date_iso(disclosure_date)
        entry = session.get(TdnetSourceDocument, url)
        if entry is None:
            entry = _register(
                session, url=url, document_id=document_id, disclosure_date=disclosure_date,
                time=time, pdf_root=pdf_root, fetch=fetch, now=now,
            )
        if entry.external_document_id != document_id or entry.disclosure_date != date_iso:
            raise SourceVerificationError(
                "contract_error", f"台帳の文書ID・公表日がTDnet行と一致しません: {url}"
            )
        return _verify(entry, pdf_root)
    except SourceContractError as exc:
        raise SourceVerificationError("contract_error", str(exc)) from exc
