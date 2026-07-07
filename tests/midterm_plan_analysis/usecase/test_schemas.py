import pytest
from pydantic import ValidationError

from midterm_plan_analysis.usecase.schemas import KeywordExtraction, MidtermKeywordExtraction


class TestKeywordExtraction:

    def test_valid_keyword(self):
        kw = KeywordExtraction(keyword="DX推進", context_raw="全社的なDX推進により業務効率化を図る")
        assert kw.keyword == "DX推進"
        assert kw.context_raw == "全社的なDX推進により業務効率化を図る"

    def test_context_raw_defaults_to_none(self):
        kw = KeywordExtraction(keyword="DX推進")
        assert kw.context_raw is None

    def test_keyword_is_required(self):
        with pytest.raises(ValidationError):
            KeywordExtraction()


class TestMidtermKeywordExtraction:

    def test_valid_extraction(self):
        obj = MidtermKeywordExtraction(
            keywords=[KeywordExtraction(keyword="DX推進"), KeywordExtraction(keyword="海外展開")]
        )
        assert len(obj.keywords) == 2

    def test_keywords_defaults_to_empty_list(self):
        obj = MidtermKeywordExtraction()
        assert obj.keywords == []
