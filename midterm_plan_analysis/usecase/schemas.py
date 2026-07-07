from typing import List, Optional

from pydantic import BaseModel


class KeywordExtraction(BaseModel):
    """1キーワード分のresponseSchema。正規化はせず生表記のまま抽出する。"""

    keyword: str
    context_raw: Optional[str] = None  # キーワードが言及されている一文程度の逐語引用


class MidtermKeywordExtraction(BaseModel):
    """キーワード抽出のresponseSchema。"""

    keywords: List[KeywordExtraction] = []
