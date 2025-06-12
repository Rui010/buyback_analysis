from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from buyback_analysis.models.announcement import Announcement
from buyback_analysis.models.completion import Completion
from buyback_analysis.models.progress import Progress
from buyback_analysis.models.correction import Correction
from buyback_analysis.usecase.logger import Logger
from buyback_analysis.consts.detect_type import DetectType

logger = Logger()


def post_data(session: Session, data: dict) -> None:
    """
    データをSQLiteデータベースに保存する関数

    Args:
        data (dict): 保存するデータ（辞書形式）

    Raises:
        ValueError: 必要な環境変数が設定されていない場合
        RuntimeError: データの保存に失敗した場合
    """
    model_map = {
        DetectType.BUYBACK_ANNOUNCEMENT: Announcement,
        DetectType.BUYBACK_PROGRESS: Progress,
        DetectType.BUYBACK_COMPLETION: Completion,
        DetectType.CORRECTION: Correction,
    }
    try:
        if data is None:
            raise ValueError("データがNoneです")
        detect_type = DetectType(data["type"])
        ModelClass = model_map[detect_type]
        instance = ModelClass(**data["data"])
        session.add(instance)

        session.commit()
        logger.info("データが正常に保存されました")
    except IntegrityError as e:
        # 主キーエラーの場合はスキップして続行
        session.rollback()
        logger.info(f"主キーエラーによりスキップしました: {e}")
    except Exception as e:
        session.rollback()
        logger.log_failed_data(data, str(e))
