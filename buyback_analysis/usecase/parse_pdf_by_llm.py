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

logger = Logger()


def _sanitize_null_strings(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sanitize_null_strings(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_null_strings(v) for v in obj]
    if obj == "null":
        return None
    return obj


def parse_pdf_by_llm(
    title: str, pdf_path: str, code: str, name: str, prompt_filename: str
) -> Optional[Dict[str, Any]]:
    """
    Gemini Files API を使ってPDFをネイティブ処理し、JSONデータを辞書で返す。
    プロンプトテンプレートに {content} プレースホルダーは不要。

    Args:
        title: IRのタイトル
        pdf_path: ローカルのPDFファイルパス
        code: 証券コード
        name: 企業名
        prompt_filename: prompts/ 配下のテンプレートファイル名

    Returns:
        パース済みのデータ（辞書形式）。失敗時は None。
    """
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEYが設定されていません")

    prompt = load_prompt_template(prompt_filename, title=title, code=code, name=name)

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
            )
            time.sleep(1)

            cleaned_text = re.sub(
                r"^```json\s*|\s*```$", "", response.text.strip(), flags=re.DOTALL
            )
            return _sanitize_null_strings(json.loads(cleaned_text))

        except APIError as e:
            if e.code in {502, 503, 504}:
                logger.info(f"サーバーエラー {e.code}が発生しました。リトライ {attempt}/{max_retries}")
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    continue
                else:
                    logger.error(f"リトライ回数を超えました: {e}")
                    raise SystemExit("Gemini APIのサーバエラーにより、プログラムを終了します。") from e
            else:
                logger.error(f"Gemini APIの制限に達しました: {e}")
                raise SystemExit("Gemini APIの制限に達したため、プログラムを終了します。")

        except json.JSONDecodeError as e:
            logger.error(f"[JSON ERROR] パース失敗: {e}")
            logger.error(f"[RAW OUTPUT] {response.text}")
            return None

        except Exception as e:
            logger.error(f"予期しないエラーが発生しました: {e}")
            return None

        finally:
            if pdf_file is not None:
                try:
                    client.files.delete(name=pdf_file.name)
                except Exception:
                    pass
