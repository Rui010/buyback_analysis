from pypdf import PdfReader
from typing import Optional

from buyback_analysis.interface.logger import Logger
from buyback_analysis.usecase.get_pdf_path import get_pdf_path

logger = Logger()


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

    try:
        with open(save_path, "rb") as pdf_file:
            reader = PdfReader(pdf_file)
            if reader.is_encrypted:
                reader.decrypt("")
            text = ""
            for page in reader.pages:
                text += page.extract_text()
        return text
    except Exception as e:
        logger.error(f"PDFファイルの読み込みに失敗しました: {e}")
        return None
