from pathlib import Path


PROMPT = Path("buyback_analysis/prompts/buyback_events.md")


def test_prompt_prevents_duplicate_or_referenced_events():
    text = PROMPT.read_text(encoding="utf-8")

    assert "completionだけ" in text
    assert "別文書で開示予定" in text
    assert "execution_noticeを作らない" in text


def test_prompt_defines_new_plan_evidence_flags_and_zero_values():
    text = PROMPT.read_text(encoding="utf-8")

    assert "company_own_transaction=true" in text
    assert "independent_resolution=true" in text
    assert "明示された0はnullにせず0" in text
    assert "累計・合計の取得株数をshares_acquired" in text
