import os
from dotenv import load_dotenv
import time
from google import genai
from google.genai.errors import APIError

from buyback_analysis.interface.load_prompt_template import load_prompt_template
from buyback_analysis.models.is_checked import IsChecked
from buyback_analysis.usecase.logger import Logger
from buyback_analysis.consts.detect_type import DetectType

logger = Logger()


def get_detect_type_in_db(session, link) -> str:
    """
    データベースから自己株式取得の種類を取得する。

    Args:
        session: SQLAlchemyのセッションオブジェクト
        link (str): 対象のURL

    Returns:
        str: 判定結果（文字列）。存在しない場合は None。
    """
    try:
        result = session.query(IsChecked).filter_by(url=link).first()
        if result is None:
            return None
        return result.detected_type  # ←カラム名に合わせて修正
    except Exception as e:
        logger.error(f"データベースからの取得に失敗しました: {e}")
        return None


def detect_type_by_llm(title: str, content: str) -> str:
    """
    Gemini APIを使って自己株式取得の種類を判定する。
    - announcement（自己株式取得の予定を初めて発表した文書）
    - progress（取得が進行中であることを報告する文書）
    - completion（取得が終了し、結果を報告する文書）

    Returns:
        type: 判定結果（文字列）。失敗時は None。
    """
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise ValueError("GEMINI_API_KEYが設定されていません")

    prompt_filename = "ir_type.md"
    prompt = load_prompt_template(prompt_filename, title=title, content=content)

    max_retries = 3
    retry_delay = 60  # 秒

    for attempt in range(1, max_retries + 1):
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model="gemini-2.0-flash-lite",
                contents=prompt,
            )
            time.sleep(1)  # レート制限対策のためのスリープ
            ir_type_str = response.text.strip()

            # 判定結果がリストに含まれているか確認
            try:
                ir_type_enum = DetectType(
                    ir_type_str
                )  # Enum変換（ここで不正値は弾かれる）
                return ir_type_enum.value  # または ir_type_enum（用途による）
            except ValueError:
                logger.error(f"判定結果が不正です: {ir_type_str}")
                return None

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

        except Exception as e:
            logger.error(f"予期しないエラーが発生しました: {e}")
            return None
