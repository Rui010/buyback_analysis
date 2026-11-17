from buyback_analysis.usecase.event_schemas import BuybackEventExtraction
from buyback_analysis.usecase.validate_event_quotes import validate_event_quotes


def _extraction(quote):
    return BuybackEventExtraction.model_validate(
        {
            "events": [
                {
                    "event_type": "new_plan",
                    "source_quote": quote,
                    "payload": {},
                }
            ]
        }
    )


def test_quote_is_verified_after_unicode_and_whitespace_normalization():
    extraction = _extraction("自己株式の取得を 決議しました。")
    source = "当社は、自己株式の取得を\n決議しました。詳細は次のとおりです。"

    result = validate_event_quotes(extraction, source)

    assert result.events[0].verified is True
    assert result.events[0].reason_code == "SOURCE_QUOTE_VERIFIED"


def test_quote_not_in_source_is_retained_but_unverified():
    extraction = _extraction("自己株式を100万株取得する。")

    result = validate_event_quotes(extraction, "自己株式取得について検討します。")

    assert result.events[0].event is extraction.events[0]
    assert result.events[0].verified is False
    assert result.events[0].reason_code == "SOURCE_QUOTE_NOT_FOUND"


def test_each_event_is_checked_independently():
    extraction = BuybackEventExtraction.model_validate(
        {
            "events": [
                {"event_type": "completion", "source_quote": "自己株式の取得をすべて終了した。", "payload": {}},
                {"event_type": "new_plan", "source_quote": "新たな取得枠を設定した。", "payload": {}},
            ]
        }
    )

    result = validate_event_quotes(extraction, "自己株式の取得をすべて終了した。")

    assert [item.verified for item in result.events] == [True, False]


def test_short_quote_is_not_accepted_even_when_present():
    extraction = _extraction("市場買付")

    result = validate_event_quotes(extraction, "取得方法は市場買付とします。")

    assert result.events[0].verified is False
    assert result.events[0].reason_code == "SOURCE_QUOTE_NOT_FOUND"
