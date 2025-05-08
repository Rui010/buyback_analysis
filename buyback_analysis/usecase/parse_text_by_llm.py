import json
import os
from pathlib import Path
import re
import time
from dotenv import load_dotenv
from google import genai
from google.genai.errors import APIError
from typing import Any, Dict, Optional


def load_prompt_template(filename: str, **kwargs) -> str:
    """
    指定されたテンプレートファイルを読み込み、変数を埋め込んで返す
    """
    base_dir = Path(__file__).resolve().parents[1]  # プロジェクトルート
    prompt_path = base_dir / "prompts" / filename

    with open(prompt_path, encoding="utf-8") as f:
        template = f.read()
    return template.format(**kwargs)


def parse_text_by_llm(
    title: str, content: str, code: str, name: str, prompt_filename: str
) -> Optional[Dict[str, Any]]:
    """
    Gemini APIを使って大株主情報のJSONデータを辞書で返す。

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
                model="gemini-2.0-flash-lite",
                contents=prompt,
            )
            # Markdownコードブロック（```json ～ ```）を除去
            cleaned_text = re.sub(
                r"^```json\s*|\s*```$", "", response.text.strip(), flags=re.DOTALL
            )
            return json.loads(cleaned_text)

        except APIError as e:  # API制限エラー
            if e.code in {502, 503, 504}:
                print(
                    f"サーバーエラー {e.status_code}が発生しました。リトライ {attempt}/{max_retries}"
                )
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    continue
                else:
                    print(f"リトライ回数を超えました: {e}")
                    raise SystemExit(
                        "Gemini APIのサーバエラーにより、プログラムを終了します。"
                    ) < e
            else:
                print(f"Gemini APIの制限に達しました: {e}")
                raise SystemExit(
                    "Gemini APIの制限に達したため、プログラムを終了します。"
                )

        except json.JSONDecodeError as e:
            print(f"[JSON ERROR] パース失敗: {e}")
            print(f"[RAW OUTPUT] {response.text}")
            return None

        except Exception as e:
            print(f"予期しないエラーが発生しました: {e}")
            return None
