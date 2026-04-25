"""
announcements テーブルの resolution_date が NULL なレコードを LLM で補完する使い捨てスクリプト。

実行方法（仮想環境をActivateしてから）:
    python -m scripts.backfill_resolution_date [--dry-run]
"""

import argparse
import json
import os
import re
import time

from dotenv import load_dotenv
from google import genai
from sqlalchemy import create_engine, text

from buyback_analysis.usecase.get_pdf_data import get_pdf_data
from buyback_analysis.usecase.logger import Logger
from buyback_analysis.consts.llm_model import LlmModel

load_dotenv()

logger = Logger()

PDF_DOWNLOAD_PATH = os.getenv("PDF_DOWNLOAD_PATH", "pdf_data")
SQLITE_DB_URL = os.getenv("SQLITE_DB_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

PROMPT_TEMPLATE = """\
以下は自己株式取得に関するIR文書です。
文書中に記載されている「自己株式取得の決議日」（取締役会や株主総会で決議された日付）を抽出してください。

出力はJSONのみ、次の形式で返してください：
{{"resolution_date": "YYYY-MM-DD"}}

日付が不明な場合は {{"resolution_date": null}} としてください。

【本文】
{content}
"""


def extract_resolution_date(content: str) -> str | None:
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = PROMPT_TEMPLATE.format(content=content)

    for attempt in range(1, 4):
        try:
            response = client.models.generate_content(
                model=LlmModel.LLM_MODEL_GEMINI.value,
                contents=prompt,
            )
            time.sleep(1)
            cleaned = re.sub(r"^```json\s*|\s*```$", "", response.text.strip(), flags=re.DOTALL)
            data = json.loads(cleaned)
            val = data.get("resolution_date")
            return None if val == "null" else val
        except Exception as e:
            logger.error(f"  LLMエラー (試行 {attempt}/3): {e}")
            if attempt < 3:
                time.sleep(60)

    return None


def main(dry_run: bool = False):
    if not SQLITE_DB_URL:
        raise ValueError("SQLITE_DB_URL が設定されていません")
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY が設定されていません")

    engine = create_engine(SQLITE_DB_URL, echo=False, future=True)

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT code, disclosure_date, url, company_name "
                "FROM announcements WHERE resolution_date IS NULL OR resolution_date = ''"
            )
        ).fetchall()

    logger.info(f"補完対象レコード数: {len(rows)} 件")
    if not rows:
        logger.info("補完対象がありません。終了します。")
        return

    success = 0
    failed = 0

    for row in rows:
        code, disclosure_date, url, company_name = row
        logger.info(f"処理中: {code} / {disclosure_date} / {url}")

        date_str = disclosure_date.replace("-", "") if disclosure_date else "unknown"
        content = get_pdf_data(url=url, pud_date_str=date_str, save_dir=PDF_DOWNLOAD_PATH)
        if content is None:
            logger.error(f"  PDF取得失敗: {url}")
            failed += 1
            continue

        resolution_date = extract_resolution_date(content)
        if not resolution_date:
            logger.warning(f"  resolution_date が抽出できませんでした: {url}")
            failed += 1
            continue

        logger.info(f"  resolution_date = {resolution_date}")

        if dry_run:
            logger.info("  [dry-run] UPDATE はスキップします")
            success += 1
            continue

        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE announcements SET resolution_date = :resolution_date "
                    "WHERE code = :code AND disclosure_date = :disclosure_date "
                    "AND (resolution_date IS NULL OR resolution_date = '')"
                ),
                {"resolution_date": resolution_date, "code": code, "disclosure_date": disclosure_date},
            )
        logger.info("  更新完了")
        success += 1

    logger.info("=" * 50)
    logger.info(f"完了: 成功={success}, 失敗={failed}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="resolution_date バックフィルスクリプト")
    parser.add_argument("--dry-run", action="store_true", help="DBを更新せずに確認だけ行う")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
