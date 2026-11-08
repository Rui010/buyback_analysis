import datetime
import os
import tempfile
import requests
from urllib.parse import urlparse
from typing import Optional

from buyback_analysis.interface.logger import Logger

logger = Logger()


def fetch_pdf(
    url: str, pud_date_str: str, save_dir: str = "data"
) -> Optional[tuple[str, Optional[datetime.datetime]]]:
    """
    PDFファイルを保存済みなら再利用し、なければダウンロードして保存する。

    ダウンロード時は同じフォルダの一時ファイルへ書き込んでから置き換えるため、
    書き込み途中で失敗しても壊れたPDFが保存先に残らない。

    Args:
        url: PDFのURL
        pud_date_str: 日付（YYYYMMDD形式）
        save_dir: 保存先ディレクトリ

    Returns:
        (ローカルのファイルパス, 取得完了時刻UTC)。既存ファイルを再利用した場合の取得時刻は None。
        ダウンロード失敗時は None。
    """
    parsed_url = urlparse(url)
    file_name = os.path.basename(parsed_url.path)

    company_dir = os.path.join(save_dir, pud_date_str)
    os.makedirs(company_dir, exist_ok=True)

    save_path = os.path.join(company_dir, file_name)

    if os.path.exists(save_path):
        return save_path, None

    try:
        response = requests.get(url)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"PDFのダウンロードに失敗しました: {e}")
        return None

    fd, tmp_path = tempfile.mkstemp(dir=company_dir, suffix=".part")
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(response.content)
        os.replace(tmp_path, save_path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    fetched_at = datetime.datetime.now(datetime.timezone.utc)

    logger.info(f"PDFファイルを保存しました: {save_path}")
    return save_path, fetched_at


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
    fetched = fetch_pdf(url, pud_date_str, save_dir)
    return None if fetched is None else fetched[0]
