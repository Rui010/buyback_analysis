import json
import os
import re
import time
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from google import genai
from google.genai.errors import APIError

from buyback_analysis.consts.llm_model import LlmModel
from buyback_analysis.interface.load_prompt_template import load_prompt_template
from buyback_analysis.interface.logger import Logger
from buyback_analysis.usecase.parse_text_by_llm import _sanitize_null_strings
from forecast_revision_analysis.usecase.schemas import Stage1Extraction

logger = Logger()

STAGE1_TEMPERATURE = 0.0


def extract_forecast_revision_stage1(
    title: str, content: str, code: str, name: str
) -> Optional[Dict[str, Any]]:
    """
    Gemini APIを使い、業績予想修正の抽出系フィールド（Stage1）をresponseSchemaで型固定して抽出する。

    Returns:
        {"type": "FORECAST_REVISION", "data": {...}} 形式の辞書。失敗時は None。
    """
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise ValueError("GEMINI_API_KEYが設定されていません")

    prompt = load_prompt_template(
        "forecast_revision_stage1.md", title=title, content=content, code=code, name=name
    )

    max_retries = 3
    retry_delay = 60  # 秒

    for attempt in range(1, max_retries + 1):
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=LlmModel.LLM_MODEL_GEMINI.value,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": Stage1Extraction,
                    "temperature": STAGE1_TEMPERATURE,
                    "max_output_tokens": 16384,
                },
            )
            time.sleep(1)  # レート制限対策のためのスリープ
            cleaned_text = re.sub(
                r"^```json\s*|\s*```$", "", response.text.strip(), flags=re.DOTALL
            )
            data = _sanitize_null_strings(json.loads(cleaned_text))
            return {"type": "FORECAST_REVISION", "data": data}

        except APIError as e:  # API制限エラー
            if e.code in {502, 503, 504}:
                logger.info(
                    f"[Stage1] サーバーエラー {e.code}が発生しました。リトライ {attempt}/{max_retries}"
                )
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    continue
                else:
                    logger.error(f"[Stage1] リトライ回数を超えました: {e}")
                    raise SystemExit(
                        "Gemini APIのサーバエラーにより、プログラムを終了します。"
                    ) from e
            else:
                logger.error(f"[Stage1] Gemini APIの制限に達しました: {e}")
                raise SystemExit(
                    "Gemini APIの制限に達したため、プログラムを終了します。"
                )

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
