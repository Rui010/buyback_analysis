from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from buyback_analysis.models.is_checked import IsChecked
from buyback_analysis.usecase.logger import Logger

logger = Logger()


def post_url(session: Session, code: str, url: str, detected_type: str) -> None:
    """
    データをSQLiteデータベースに保存する関数

    Args:
        data (dict): 保存するデータ（辞書形式）

    Raises:
        ValueError: 必要な環境変数が設定されていない場合
        RuntimeError: データの保存に失敗した場合
    """

    try:
        is_checked = IsChecked(
            code=code,
            url=url,
            detected_type=detected_type,
        )
        session.add(is_checked)
        session.commit()
        logger.info("データが正常に保存されました")
    except IntegrityError as e:
        # 主キーエラーの場合はスキップして続行
        session.rollback()
        logger.info(f"主キーエラーによりスキップしました: {e}")
    except Exception as e:
        session.rollback()
