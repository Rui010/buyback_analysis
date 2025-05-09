import os
from pypdf import PdfReader
from dotenv import load_dotenv
import requests
from urllib.parse import urlparse


def get_pdf_data(url: str, pud_date_str: str, save_dir="data") -> bytes:
    """
    PDFファイルを取得し、テキストデータを抽出する関数
    Args:
        url (str): pdfのURL
        pud_date_str (str): 日付（YYYYMMDD形式）
        save_dir (str): 保存先ディレクトリ

    Returns:
        str: XBRLファイルのバイナリデータ

    Raises:
        ValueError: 必要な環境変数が設定されていない場合
        RuntimeError: APIリクエストが失敗した場合
    """
    # URLからファイル名を抽出
    parsed_url = urlparse(url)
    file_name = os.path.basename(parsed_url.path)

    company_dir = os.path.join(save_dir, pud_date_str)
    os.makedirs(company_dir, exist_ok=True)

    save_path = os.path.join(company_dir, file_name)

    # 存在しない場合は、ダウンロードする
    if os.path.exists(save_path) == False:
        # リクエスト
        try:
            response = requests.get(url)
            response.raise_for_status()  # HTTPエラーが発生した場合に例外をスロー
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"ダウンロードに失敗しました: {e}")

        # PDFファイルの保存
        with open(save_path, "wb") as out:
            out.write(response.content)

        print(f"PDFファイルを保存しました: {save_path}")

    # PDFファイルの読み込み、テキストデータの抽出
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
        print(f"PDFファイルの読み込みに失敗しました: {e}")
        return None
