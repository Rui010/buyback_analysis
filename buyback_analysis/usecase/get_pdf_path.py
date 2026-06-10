import os
import requests
from urllib.parse import urlparse
from typing import Optional

from buyback_analysis.interface.logger import Logger

logger = Logger()


def get_pdf_path(url: str, pud_date_str: str, save_dir: str = "data") -> Optional[str]:
    """
    PDFファイルをダウンロードしてローカルパスを返す。

    Args:
        url: PDFのURL
        pud_date_str: 日付（YYYYMMDD形式）
        save_dir: 保存先ディレクトリ

    Returns:
        ローカルのファイルパス。ダウンロード失敗時は None。
    """
    parsed_url = urlparse(url)
    file_name = os.path.basename(parsed_url.path)

    company_dir = os.path.join(save_dir, pud_date_str)
    os.makedirs(company_dir, exist_ok=True)

    save_path = os.path.join(company_dir, file_name)

    if not os.path.exists(save_path):
        try:
            response = requests.get(url)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error(f"PDFのダウンロードに失敗しました: {e}")
            return None

        with open(save_path, "wb") as out:
            out.write(response.content)

        logger.info(f"PDFファイルを保存しました: {save_path}")

    return save_path
