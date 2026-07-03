import json
import os
import re
import time
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from google import genai
from google.genai.errors import APIError
from pypdf import PdfReader

from buyback_analysis.consts.llm_model import LlmModel
from buyback_analysis.interface.load_prompt_template import load_prompt_template
from buyback_analysis.interface.logger import Logger
from buyback_analysis.usecase.parse_text_by_llm import _sanitize_null_strings
from forecast_revision_analysis.usecase.schemas import Stage1Extraction

logger = Logger()

STAGE1_TEMPERATURE = 0.0
LEAD_TEXT_MAX_CHARS = 1000


def _extract_lead_text(pdf_path: str, max_chars: int = LEAD_TEXT_MAX_CHARS) -> str:
    """
    PDF1ページ目冒頭のテキストを抽出する。

    ネイティブPDF方式（Gemini Files APIでの画像的な読み取り）は、ヘッダー情報が密集した
    1ページ目冒頭の書き出し段落（前回予想の公表日など）を読み落とすことがあるため、
    プロンプトへの補助情報として渡す。抽出に失敗してもネイティブPDF方式自体は継続できるよう、
    例外は握りつぶして空文字列を返す。
    """
    try:
        with open(pdf_path, "rb") as pdf_file:
            reader = PdfReader(pdf_file)
            if reader.is_encrypted:
                reader.decrypt("")
            text = reader.pages[0].extract_text() or ""
        return text[:max_chars]
    except Exception as e:
        logger.info(f"[Stage1] 補助テキスト抽出に失敗しました（無視して続行）: {e}")
        return ""


def extract_forecast_revision_stage1_native(
    title: str, pdf_path: str, code: str, name: str
) -> Optional[Dict[str, Any]]:
    """
    Gemini Files API を使ってPDFをネイティブ処理し、業績予想修正の抽出系フィールド（Stage1）を
    responseSchemaで型固定して抽出する。

    Returns:
        {"type": "FORECAST_REVISION", "data": {...}} 形式の辞書。失敗時は None。
    """
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEYが設定されていません")

    lead_text = _extract_lead_text(pdf_path) or "（抽出できませんでした）"
    prompt = load_prompt_template(
        "forecast_revision_stage1_native.md", title=title, code=code, name=name, lead_text=lead_text
    )

    max_retries = 3
    retry_delay = 60

    for attempt in range(1, max_retries + 1):
        pdf_file = None
        try:
            client = genai.Client(api_key=api_key)

            pdf_file = client.files.upload(
                file=pdf_path,
                config={"mime_type": "application/pdf"},
            )

            response = client.models.generate_content(
                model=LlmModel.LLM_MODEL_GEMINI.value,
                contents=[pdf_file, prompt],
                config={
                    "response_mime_type": "application/json",
                    "response_schema": Stage1Extraction,
                    "temperature": STAGE1_TEMPERATURE,
                    "max_output_tokens": 16384,
                },
            )
            time.sleep(1)

            cleaned_text = re.sub(
                r"^```json\s*|\s*```$", "", response.text.strip(), flags=re.DOTALL
            )
            data = _sanitize_null_strings(json.loads(cleaned_text))
            return {"type": "FORECAST_REVISION", "data": data}

        except APIError as e:
            if e.code in {502, 503, 504}:
                logger.info(f"[Stage1] サーバーエラー {e.code}が発生しました。リトライ {attempt}/{max_retries}")
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    continue
                else:
                    logger.error(f"[Stage1] リトライ回数を超えました: {e}")
                    raise SystemExit("Gemini APIのサーバエラーにより、プログラムを終了します。") from e
            else:
                logger.error(f"[Stage1] Gemini APIの制限に達しました: {e}")
                raise SystemExit("Gemini APIの制限に達したため、プログラムを終了します。")

        except json.JSONDecodeError as e:
            logger.error(f"[Stage1][JSON ERROR] パース失敗 (attempt {attempt}/{max_retries}): {e}")
            logger.error(f"[Stage1][RAW OUTPUT] {response.text}")
            if attempt < max_retries:
                time.sleep(retry_delay)
                continue
            return None

        except Exception as e:
            logger.error(f"[Stage1] 予期しないエラーが発生しました: {e}")
            return None

        finally:
            if pdf_file is not None:
                try:
                    client.files.delete(name=pdf_file.name)
                except Exception:
                    pass
