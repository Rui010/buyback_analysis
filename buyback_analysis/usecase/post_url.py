from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from buyback_analysis.models.is_checked import IsChecked
from buyback_analysis.interface.logger import Logger

logger = Logger()


def post_url(session: Session, code: str, url: str, detected_type: str) -> None:
    """
    URLと検出タイプを is_checked テーブルに保存する関数。
    URL が既存の場合（失敗レコードの再試行）は parse_status を pending にリセットする。

    Args:
        session: SQLAlchemyのセッション
        code: 証券コード
        url: 対象のURL
        detected_type: 検出されたドキュメントタイプ
    """
    try:
        is_checked = IsChecked(
            code=code,
            url=url,
            detected_type=detected_type,
            parse_status="pending",
        )
        session.add(is_checked)
        session.commit()
        logger.info(f"is_checked に登録しました: {url}")
    except IntegrityError:
        # URL重複 = 失敗レコードの再試行。pending にリセットして再パースへ
        session.rollback()
        session.query(IsChecked).filter_by(url=url).update(
            {"detected_type": detected_type, "parse_status": "pending"}
        )
        session.commit()
        logger.info(f"失敗レコードを pending にリセットしました: {url}")
    except Exception as e:
        session.rollback()
        logger.error(f"URLの保存に失敗しました: {url} - {e}")


def update_parse_status(session: Session, url: str, status: str) -> None:
    """
    is_checked の parse_status を更新する。

    Args:
        session: SQLAlchemyのセッション
        url: 対象のURL
        status: 新しいステータス（saved / failed / pending / skipped）
    """
    try:
        session.query(IsChecked).filter_by(url=url).update({"parse_status": status})
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"parse_status の更新に失敗しました: {url} - {e}")
