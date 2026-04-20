from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from buyback_analysis.models.announcement import Announcement
from buyback_analysis.models.completion import Completion
from buyback_analysis.models.progress import Progress
from buyback_analysis.models.correction import Correction
from buyback_analysis.models.retirement import Retirement
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
    # 必須フィールドの定義
    required_fields = {
        DetectType.BUYBACK_ANNOUNCEMENT: ["code", "disclosure_date"],
        DetectType.BUYBACK_PROGRESS: ["code", "disclosure_date"],
        DetectType.BUYBACK_COMPLETION: ["code", "disclosure_date"],
        DetectType.CORRECTION: ["code", "disclosure_date"],
        DetectType.RETIREMENT: ["code", "disclosure_date"],
    }

    model_map = {
        DetectType.BUYBACK_ANNOUNCEMENT: Announcement,
        DetectType.BUYBACK_PROGRESS: Progress,
        DetectType.BUYBACK_COMPLETION: Completion,
        DetectType.CORRECTION: Correction,
        DetectType.RETIREMENT: Retirement,
    }
    try:
        if data is None:
            raise ValueError("データがNoneです")
        detect_type = DetectType(data["type"])

        # LLM出力のバリデーション：必須フィールドがNULLでないことを確認
        required = required_fields.get(detect_type, [])
        for field in required:
            if field not in data["data"] or data["data"][field] is None:
                logger.error(
                    f"必須フィールド '{field}' がNULLまたは存在しません: {data}"
                )
                raise ValueError(f"必須フィールド '{field}' が不足しています")

        ModelClass = model_map[detect_type]
        columns = {c.key for c in inspect(ModelClass).mapper.column_attrs}
        filtered = {k: v for k, v in data["data"].items() if k in columns}
        instance = ModelClass(**filtered)
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
