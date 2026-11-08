"""TDnet原典の識別規則（tdnet-provenance-v1 §4.2）。

`ir_analytics_contract.tdnet` / `tdnet_sources` と同じ規則を、依頼元パッケージに
依存せず実装している。
"""

import datetime
import hashlib
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID, uuid5

# ir_analytics_contract.tdnet.TDNET_NAMESPACE と同値
TDNET_NAMESPACE = UUID("d86f2629-2188-4ef6-90db-aeddb5f79b45")
STORAGE_URI_PREFIX = "tdnet-pdf://"
JST = datetime.timezone(datetime.timedelta(hours=9))


class SourceContractError(ValueError):
    """URL・文書ID・保存URIが原典識別規則に合わない。"""


def external_document_id(url: str) -> str:
    filename = urlparse(url or "").path.rsplit("/", 1)[-1]
    if not filename.endswith(".pdf"):
        raise SourceContractError(f"TDnet URLがPDFを指していません: {url}")
    document_id = filename.removesuffix(".pdf")
    if not document_id:
        raise SourceContractError(f"TDnet URLから文書IDを取得できません: {url}")
    return document_id


def _to_date(value) -> datetime.date:
    if isinstance(value, datetime.datetime):  # pandas.Timestampを含む
        return value.date()
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value).strip().replace("/", "-"))
    except ValueError as exc:
        raise SourceContractError(f"TDnet公表日が不正です: {value}") from exc


def disclosure_folder(value) -> str:
    return _to_date(value).strftime("%Y%m%d")


def disclosure_date_iso(value) -> str:
    return _to_date(value).isoformat()


def build_storage_uri(folder: str, document_id: str) -> str:
    return f"{STORAGE_URI_PREFIX}{folder}/{document_id}.pdf"


def resolve_storage_path(pdf_root, storage_uri: str, document_id: str) -> Path:
    if not storage_uri.startswith(STORAGE_URI_PREFIX):
        raise SourceContractError(f"tdnet-pdf URIではありません: {storage_uri}")
    if not storage_uri.casefold().endswith(f"/{document_id}.pdf".casefold()):
        raise SourceContractError(f"storage_uriと文書IDが一致しません: {storage_uri}")
    root = Path(pdf_root).resolve()
    path = (root / Path(*storage_uri.removeprefix(STORAGE_URI_PREFIX).split("/"))).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise SourceContractError(f"storage_uriがPDFルート外を指しています: {storage_uri}") from exc
    return path


def sha256_file(path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_published_at(disclosure_date, time_value) -> str | None:
    """TDnetのdate + time（JST）をUTC offset付きISO8601にする。timeが不明ならNone。"""
    if not time_value:
        return None
    try:
        parsed = datetime.datetime.strptime(str(time_value).strip(), "%H:%M").time()
    except ValueError:
        return None
    return datetime.datetime.combine(_to_date(disclosure_date), parsed, tzinfo=JST).isoformat()


def source_document_id(document_id: str) -> str:
    return str(uuid5(TDNET_NAMESPACE, f"tdnet:{document_id}"))
