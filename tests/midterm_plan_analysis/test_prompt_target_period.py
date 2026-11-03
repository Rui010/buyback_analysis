from pathlib import Path

import pytest


PROMPT_DIR = Path(__file__).parents[2] / "buyback_analysis" / "prompts"


@pytest.mark.parametrize("filename", ["midterm_plan.md", "midterm_plan_native.md"])
def test_midterm_plan_prompt_defines_target_period_fields(filename):
    prompt = (PROMPT_DIR / filename).read_text(encoding="utf-8")

    assert '"target_period_label"' in prompt
    assert '"target_fiscal_end"' in prompt
    assert "資料に記載された期間表記" in prompt
    assert '"YYYY/MM"' in prompt
    assert "判断できなければ `null`" in prompt


@pytest.mark.parametrize("filename", ["midterm_plan.md", "midterm_plan_native.md"])
def test_midterm_plan_prompt_preserves_target_year_and_limits_normalization(filename):
    prompt = (PROMPT_DIR / filename).read_text(encoding="utf-8")

    assert "資料に記載された年の数字をそのまま" in prompt
    assert "決算月だけを根拠に" in prompt
    assert "3カ年累計" in prompt
