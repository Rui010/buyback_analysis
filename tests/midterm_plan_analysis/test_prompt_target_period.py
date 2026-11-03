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


@pytest.mark.parametrize("filename", ["midterm_plan.md", "midterm_plan_native.md"])
def test_midterm_plan_prompt_excludes_non_midterm_targets(filename):
    prompt = (PROMPT_DIR / filename).read_text(encoding="utf-8")

    assert "単年度の業績予想" in prompt
    assert "業績予想の修正" in prompt
    assert "役員報酬" in prompt
    assert "質疑応答" in prompt
    assert "外部統計" in prompt
    assert "市場予測" in prompt


@pytest.mark.parametrize("filename", ["midterm_plan.md", "midterm_plan_native.md"])
def test_midterm_plan_prompt_handles_corrections_and_long_term_targets(filename):
    prompt = (PROMPT_DIR / filename).read_text(encoding="utf-8")

    assert "訂正後の目標値" in prompt
    assert "訂正前の値" in prompt
    assert "長期ビジョン" in prompt
    assert "計画期間内" in prompt
    assert '"metrics": []' in prompt


@pytest.mark.parametrize("filename", ["midterm_plan.md", "midterm_plan_native.md"])
def test_midterm_plan_prompt_defines_plan_period_fields(filename):
    prompt = (PROMPT_DIR / filename).read_text(encoding="utf-8")

    assert '"plan_start_period_label"' in prompt
    assert '"plan_end_period_label"' in prompt
    assert '"plan_start_fiscal_end"' in prompt
    assert '"plan_end_fiscal_end"' in prompt
    assert "開始・終了の片方だけ" in prompt
    assert "計画名や目標年度から推測" in prompt
