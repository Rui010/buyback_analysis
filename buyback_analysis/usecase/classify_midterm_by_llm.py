import json
import os
import re
import time
from dotenv import load_dotenv
from google import genai
from google.genai.errors import APIError

from buyback_analysis.interface.load_prompt_template import load_prompt_template
from buyback_analysis.interface.llm_usage import report_llm_response
from buyback_analysis.interface.logger import Logger
from buyback_analysis.consts.llm_model import LlmModel

logger = Logger()

PROMPT_FILENAME = "classify_midterm.md"

# generate_content()に渡す設定。processing_runのgeneration_config・reuse keyにも同じ値を使う
GENERATION_CONFIG = {}
# 出力の解析処理（JSON整形・null正規化等）を変えたら上げる。reuse keyに含まれ、古い解析結果の再利用を防ぐ
EXTRACTOR_VERSION = "classify_midterm_by_llm:1"


def classify_midterm_by_llm(
    title: str, content: str, code: str, name: str
) -> str:
    """
    metricsが空だった中計文書を分類する。

    Returns:
        "withdrawn" | "no_targets" | "postponed" | "failed"（LLMエラー時）
    """
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise ValueError("GEMINI_API_KEYが設定されていません")

    prompt = load_prompt_template(
        PROMPT_FILENAME, title=title, content=content, code=code, name=name
    )

    max_retries = 3
    retry_delay = 60

    for attempt in range(1, max_retries + 1):
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=LlmModel.LLM_MODEL_GEMINI.value,
                contents=prompt,
                config=GENERATION_CONFIG or None,  # 空なら従来どおり設定を渡さない
            )
            report_llm_response(response)
            time.sleep(1)
            cleaned_text = re.sub(
                r"^```json\s*|\s*```$", "", response.text.strip(), flags=re.DOTALL
            )
            result = json.loads(cleaned_text)
            status = result.get("extraction_status")
            if status in {"withdrawn", "no_targets", "postponed"}:
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
