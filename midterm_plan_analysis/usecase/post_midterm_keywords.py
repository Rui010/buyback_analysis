from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from buyback_analysis.interface.logger import Logger
from midterm_plan_analysis.models.midterm_plan_keyword import MidtermPlanKeyword

logger = Logger()


def post_midterm_keywords(
    session: Session,
    code: str,
    url: str,
    disclosure_date: str,
    keywords: Optional[List[Dict[str, Any]]],
    commit: bool = True,
) -> bool:
    """
    中期経営計画のキーワードを1キーワード1行としてSQLiteに保存する。

    keywordsがNoneまたは空の場合は何も保存しない（抽出失敗時にmetrics側のデータ保存を
    ブロックしないよう、main.py側でNoneのまま呼び出される）。

    LLMが同一文書内で同じkeyword（完全一致）を重複して返す場合があるため、
    UniqueConstraint(code, url, keyword)違反でこの文書のキーワードが全件ロールバックされる
    ことがないよう、保存前にkeyword単位で重複除去する（先勝ち）。

    commit=Falseならcommitせずflushだけ行い、失敗時のrollbackも呼び出し側に任せる
    （採用版切替のトランザクションに含めるため）。

    Returns:
        保存した（または保存対象がなかった）場合 True。保存に失敗した場合 False。
    """
    if not keywords:
        return True

    deduped: Dict[str, Dict[str, Any]] = {}
    for kw in keywords:
        deduped.setdefault(kw["keyword"], kw)

    for kw in deduped.values():
        session.add(
            MidtermPlanKeyword(
                code=code,
                url=url,
                keyword=kw["keyword"],
                context_raw=kw.get("context_raw"),
                disclosure_date=disclosure_date,
            )
        )

    try:
        session.commit() if commit else session.flush()
        logger.info(f"中期経営計画のキーワードを保存しました: {code} - {url} ({len(deduped)}件)")
        return True
    except IntegrityError:
        if commit:
            session.rollback()
        logger.info(f"主キーエラーによりスキップしました: {code} - {url}")
        return False
    except Exception as e:
        if commit:
            session.rollback()
        logger.error(f"キーワードの保存に失敗しました: {code} - {url} - {e}")
        return False
