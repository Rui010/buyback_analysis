"""LLMへ渡すPDF入力の準備（中計・会社予想修正・キーワードbackfill共通）。"""

from dataclasses import dataclass

from buyback_analysis.usecase.get_pdf_data import (
    extract_pdf_pages,
    extract_pdf_text,
    format_pages_with_markers,
    get_pdf_data,
)
from buyback_analysis.usecase.get_pdf_path import get_pdf_path
from tdnet_provenance.usecase.provenance_recorder import ProvenanceRecorder
from tdnet_provenance.usecase.resolve_verified_source import VerifiedSource


@dataclass(frozen=True)
class PdfInput:
    """native方式ならpdf_path、text方式ならcontentのどちらか一方を持つ。

    paged_contentはtext方式でpage_markers=Trueのときだけ持つ、ページの目印入りの本文（中計のmetrics用）。
    """

    source: VerifiedSource | None  # provenance無効時はNone
    pdf_path: str | None
    content: str | None
    paged_content: str | None = None


def _read_pages(pdf_path: str) -> PdfInput | None:
    """ページごとに1回だけ読み、目印なし（content）と目印あり（paged_content）の両方を作る。"""
    pages = extract_pdf_pages(pdf_path)
    if pages is None:
        return None
    try:
        content = "".join(pages)
    except TypeError:  # extract_text()がNoneを返したページがある（extract_pdf_textと同じく失敗扱い）
        return None
    return PdfInput(source=None, pdf_path=None, content=content, paged_content=format_pages_with_markers(pages))


def prepare_pdf_input(
    recorder: ProvenanceRecorder | None,
    *,
    url: str,
    disclosure_date,
    time,
    pud_date_str: str,
    pdf_root: str,
    use_native: bool,
    stage: str,
    page_markers: bool = False,
) -> PdfInput | None:
    """PDF入力を用意する。取得・照合・読取に失敗したらNone。

    recorderがあれば台帳照合済みのPDFだけを使い、失敗はfailed runとして記録する
    （disclosure_date・timeはTDnet行の値）。recorderがなければ従来どおり
    pud_date_strのフォルダから取得する。page_markers=Trueならtext方式でpaged_contentも用意する
    （native方式では無視する）。
    """
    if recorder is None:
        if use_native:
            pdf_path = get_pdf_path(url=url, pud_date_str=pud_date_str, save_dir=pdf_root)
            return None if pdf_path is None else PdfInput(source=None, pdf_path=pdf_path, content=None)
        if page_markers:
            pdf_path = get_pdf_path(url=url, pud_date_str=pud_date_str, save_dir=pdf_root)
            return None if pdf_path is None else _read_pages(pdf_path)
        content = get_pdf_data(url=url, pud_date_str=pud_date_str, save_dir=pdf_root)
        return None if content is None else PdfInput(source=None, pdf_path=None, content=content)

    source = recorder.resolve_source(
        url=url, disclosure_date=disclosure_date, time=time, pdf_root=pdf_root, stage=stage,
    )
    if source is None:
        return None
    if use_native:
        return PdfInput(source=source, pdf_path=str(source.path), content=None)
    if page_markers:
        paged = _read_pages(str(source.path))
        if paged is None:
            recorder.record_source_failure(url=url, stage=stage, error_code="pdf_read_failed", source=source)
            return None
        return PdfInput(source=source, pdf_path=None, content=paged.content, paged_content=paged.paged_content)
    content = extract_pdf_text(str(source.path))
    if content is None:
        recorder.record_source_failure(url=url, stage=stage, error_code="pdf_read_failed", source=source)
        return None
    return PdfInput(source=source, pdf_path=None, content=content)
