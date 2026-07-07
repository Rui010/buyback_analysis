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
from midterm_plan_analysis.usecase.schemas import MidtermKeywordExtraction

logger = Logger()

KEYWORDS_TEMPERATURE = 0.0


def extract_midterm_keywords_native(
    title: str, pdf_path: str, code: str, name: str
) -> Optional[Dict[str, Any]]:
    """
    Gemini Files API を使ってPDFをネイティブ処理し、戦略テーマ・重点施策のキーワードを
    responseSchemaで型固定して抽出する。metrics抽出（既存の`midterm_plan_native.md`）とは
    別コールにする。

    Returns:
        {"type": "MIDTERM_PLAN", "data": {"keywords": [...]}} 形式の辞書。失敗時は None。
    """
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEYが設定されていません")

    prompt = load_prompt_template("midterm_keywords_native.md", title=title, code=code, name=name)

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
                    "response_schema": MidtermKeywordExtraction,
                    "temperature": KEYWORDS_TEMPERATURE,
                    "max_output_tokens": 2048,
                },
            )
            time.sleep(1)

            cleaned_text = re.sub(
                r"^```json\s*|\s*```$", "", response.text.strip(), flags=re.DOTALL
            )
            data = _sanitize_null_strings(json.loads(cleaned_text))
            return {"type": "MIDTERM_PLAN", "data": data}

        except APIError as e:
            if e.code in {502, 503, 504}:
                logger.info(f"[Keywords] サーバーエラー {e.code}が発生しました。リトライ {attempt}/{max_retries}")
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    continue
                else:
                    logger.error(f"[Keywords] リトライ回数を超えました: {e}")
                    raise SystemExit("Gemini APIのサーバエラーにより、プログラムを終了します。") from e
            else:
                logger.error(f"[Keywords] Gemini APIの制限に達しました: {e}")
                raise SystemExit("Gemini APIの制限に達したため、プログラムを終了します。")

        except json.JSONDecodeError as e:
            logger.error(f"[Keywords][JSON ERROR] パース失敗 (attempt {attempt}/{max_retries}): {e}")
            logger.error(f"[Keywords][RAW OUTPUT] {response.text}")
            if attempt < max_retries:
                time.sleep(retry_delay)
                continue
            return None

        except Exception as e:
            logger.error(f"[Keywords] 予期しないエラーが発生しました: {e}")
            return None

        finally:
            if pdf_file is not None:
                try:
                    client.files.delete(name=pdf_file.name)
                except Exception:
                    pass
