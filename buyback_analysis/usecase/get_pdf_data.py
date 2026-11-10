from pypdf import PdfReader
from typing import Optional

from buyback_analysis.interface.logger import Logger
from buyback_analysis.usecase.get_pdf_path import get_pdf_path

logger = Logger()


def extract_pdf_pages(pdf_path: str) -> Optional[list[str]]:
    """
    保存済みPDFからページごとのテキストを抽出する。

    Args:
        pdf_path: PDFのローカルパス

    Returns:
        ページ順のテキストのリスト。失敗時は None。
    """
    try:
        with open(pdf_path, "rb") as pdf_file:
            reader = PdfReader(pdf_file)
            if reader.is_encrypted:
                reader.decrypt("")
            return [page.extract_text() for page in reader.pages]
    except Exception as e:
        logger.error(f"PDFファイルの読み込みに失敗しました: {e}")
        return None


def extract_pdf_text(pdf_path: str) -> Optional[str]:
    """
    保存済みPDFからテキストを抽出する（全ページを区切りなしで連結）。

    Args:
        pdf_path: PDFのローカルパス

    Returns:
        抽出したテキスト文字列。失敗時は None。
    """
    pages = extract_pdf_pages(pdf_path)
    if pages is None:
        return None
    try:
        return "".join(pages)
    except Exception as e:  # extract_text()がNoneを返したページがある場合（従来どおり失敗扱い）
        logger.error(f"PDFファイルの読み込みに失敗しました: {e}")
        return None


def format_pages_with_markers(pages: list[str]) -> str:
    """各ページの本文の前に「--- page N ---」（1始まり）を入れて連結する。LLMにページ番号を判断させる入力用。"""
    return "\n".join(f"--- page {number} ---\n{text or ''}" for number, text in enumerate(pages, start=1))


def get_pdf_data(url: str, pud_date_str: str, save_dir: str = "data") -> Optional[str]:
    """
    PDFファイルを取得し、テキストデータを抽出する。

    Args:
        url: PDFのURL
        pud_date_str: 日付（YYYYMMDD形式）
        save_dir: 保存先ディレクトリ

    Returns:
        抽出したテキスト文字列。失敗時は None。
    """
    save_path = get_pdf_path(url, pud_date_str, save_dir)
    if save_path is None:
        return None
    return extract_pdf_text(save_path)
