import json
import os
from pathlib import Path
import re
import time
from dotenv import load_dotenv
from google import genai
from google.genai.errors import APIError
from typing import Any, Dict, Optional

from buyback_analysis.interface.load_prompt_template import load_prompt_template
from buyback_analysis.usecase.logger import Logger
from buyback_analysis.consts.llm_model import LlmModel

logger = Logger()


def parse_text_by_llm(
    title: str, content: str, code: str, name: str, prompt_filename: str
) -> Optional[Dict[str, Any]]:
    """
    Gemini APIを使ってJSONデータを辞書で返す。

    Returns:
        dict: パース済みのデータ（辞書形式）。失敗時は None。
    """
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise ValueError("GEMINI_API_KEYが設定されていません")

    prompt = load_prompt_template(
        prompt_filename, title=title, content=content, code=code, name=name
    )

    max_retries = 3
    retry_delay = 60  # 秒

    for attempt in range(1, max_retries + 1):
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=LlmModel.LLM_MODEL_GEMINI.value,
                contents=prompt,
            )
            time.sleep(1)  # レート制限対策のためのスリープ
            # Markdownコードブロック（```json ～ ```）を除去
            cleaned_text = re.sub(
                r"^```json\s*|\s*```$", "", response.text.strip(), flags=re.DOTALL
            )
            return json.loads(cleaned_text)

        except APIError as e:  # API制限エラー
            if e.code in {502, 503, 504}:
                logger.info(
                    f"サーバーエラー {e.code}が発生しました。リトライ {attempt}/{max_retries}"
                )
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    continue
                else:
                    logger.error(f"リトライ回数を超えました: {e}")
                    raise SystemExit(
                        "Gemini APIのサーバエラーにより、プログラムを終了します。"
                    ) < e
            else:
                logger.error(f"Gemini APIの制限に達しました: {e}")
                raise SystemExit(
                    "Gemini APIの制限に達したため、プログラムを終了します。"
                )

        except json.JSONDecodeError as e:
            logger.error(f"[JSON ERROR] パース失敗: {e}")
            logger.error(f"[RAW OUTPUT] {response.text}")
            return None

        except Exception as e:
            logger.error(f"予期しないエラーが発生しました: {e}")
            return None
