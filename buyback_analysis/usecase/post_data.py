from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from buyback_analysis.models.announcement import Announcement
from buyback_analysis.models.completion import Completion
from buyback_analysis.models.progress import Progress
from buyback_analysis.models.correction import Correction
from buyback_analysis.models.retirement import Retirement
from buyback_analysis.interface.logger import Logger
from buyback_analysis.consts.detect_type import DetectType

logger = Logger()


def describe_integrity_error(e: IntegrityError) -> str:
    """IntegrityErrorの種類をログ表示用の文言に変換する（NOT NULL違反を一意制約違反と誤表示しないため）。"""
    message = str(e.orig)
    if "NOT NULL constraint failed" in message:
        return "NOT NULL制約違反"
    if "UNIQUE constraint failed" in message:
        return "一意制約違反"
    return "制約違反"


def post_data(session: Session, data: dict) -> bool:
    """
    データをSQLiteデータベースに保存する関数

    Args:
        data (dict): 保存するデータ（辞書形式）

    Raises:
        ValueError: 必要な環境変数が設定されていない場合
        RuntimeError: データの保存に失敗した場合

    Returns:
        True: 保存に成功した場合
        False: DB制約違反（一意制約・NOT NULL制約など）により保存されなかった場合
    """
    # 必須フィールドの定義
    required_fields = {
        DetectType.BUYBACK_ANNOUNCEMENT: ["code", "disclosure_date"],
        DetectType.BUYBACK_PROGRESS: ["code", "disclosure_date"],
        DetectType.BUYBACK_COMPLETION: ["code", "disclosure_date", "shares_acquired", "amount_spent_yen"],
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
        return True
    except IntegrityError as e:
        session.rollback()
        logger.error(f"{describe_integrity_error(e)}により保存されませんでした: {e}")
        return False
    except Exception as e:
        session.rollback()
        logger.log_failed_data(data, str(e))
        raise
