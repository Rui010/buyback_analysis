import json
import os
import re
import time
from dotenv import load_dotenv
from google import genai
from google.genai.errors import APIError

from buyback_analysis.interface.load_prompt_template import load_prompt_template
from buyback_analysis.interface.logger import Logger
from buyback_analysis.consts.llm_model import LlmModel

logger = Logger()


def classify_midterm_by_llm(
    title: str, content: str, code: str, name: str
) -> str:
    """
    metricsが空だった中計文書を分類する。

    Returns:
        "withdrawn" | "no_targets" | "failed"（LLMエラー時）
    """
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise ValueError("GEMINI_API_KEYが設定されていません")

    prompt = load_prompt_template(
        "classify_midterm.md", title=title, content=content, code=code, name=name
    )

    max_retries = 3
    retry_delay = 60

    for attempt in range(1, max_retries + 1):
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=LlmModel.LLM_MODEL_GEMINI.value,
                contents=prompt,
            )
            time.sleep(1)
            cleaned_text = re.sub(
                r"^```json\s*|\s*```$", "", response.text.strip(), flags=re.DOTALL
            )
            result = json.loads(cleaned_text)
            status = result.get("extraction_status")
            if status in {"withdrawn", "no_targets"}:
                return status
            logger.error(f"分類プロンプトが予期しない値を返しました: {status}")
            return "failed"

        except APIError as e:
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
                    ) from e
            else:
                logger.error(f"Gemini APIの制限に達しました: {e}")
                raise SystemExit(
                    "Gemini APIの制限に達したため、プログラムを終了します。"
                )

        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"分類プロンプトの処理に失敗しました: {e}")
            return "failed"
