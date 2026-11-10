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
    # 見直し前の目標・長期目標も捨てずに、属性を付けて返す（引継ぎ仕様 4.1）
    prompt = (PROMPT_DIR / filename).read_text(encoding="utf-8")

    assert "計画期間の内外を問わずすべて" in prompt
    assert "長期ビジョン" in prompt
    assert "`long_term`" in prompt
    assert "見直し前の値も捨てずに `previous`" in prompt
    assert "訂正前" in prompt
    assert '"metrics": []' in prompt


@pytest.mark.parametrize("filename", ["midterm_plan.md", "midterm_plan_native.md"])
def test_midterm_plan_prompt_defines_target_attributes(filename):
    prompt = (PROMPT_DIR / filename).read_text(encoding="utf-8")

    for field in ("target_scope", "revision_role", "consolidation_label", "bound", "value_upper",
                  "value_text", "page"):
        assert f'"{field}"' in prompt
    for scope in ("plan_final", "plan_interim", "long_term", "cumulative", "unknown"):
        assert f"`{scope}`" in prompt
    assert "推測せず `null`" in prompt
    assert "`value` には文字列を入れないでください" in prompt


@pytest.mark.parametrize("filename", ["midterm_plan.md", "midterm_plan_native.md"])
def test_midterm_plan_prompt_defines_reference_values(filename):
    prompt = (PROMPT_DIR / filename).read_text(encoding="utf-8")

    assert '"reference_values"' in prompt
    for kind in ("actual", "estimate", "forecast", "unknown"):
        assert f"`{kind}`" in prompt
    assert '"period_label"' in prompt
    assert '"period_fiscal_end"' in prompt
    assert "同じ値を `metrics` と `reference_values` の両方に入れないでください" in prompt


def test_text_prompt_uses_page_markers():
    prompt = (PROMPT_DIR / "midterm_plan.md").read_text(encoding="utf-8")
    assert "--- page N ---" in prompt
    assert "目印がなければ推測せず `null`" in prompt


def test_native_prompt_uses_pdf_page_numbers():
    prompt = (PROMPT_DIR / "midterm_plan_native.md").read_text(encoding="utf-8")
    assert "--- page N ---" not in prompt
    assert "PDFの何ページ目か" in prompt


@pytest.mark.parametrize("filename", ["midterm_plan.md", "midterm_plan_native.md"])
def test_midterm_plan_prompt_defines_plan_period_fields(filename):
    prompt = (PROMPT_DIR / filename).read_text(encoding="utf-8")

    assert '"plan_start_period_label"' in prompt
    assert '"plan_end_period_label"' in prompt
    assert '"plan_start_fiscal_end"' in prompt
    assert '"plan_end_fiscal_end"' in prompt
    assert "開始・終了の片方だけ" in prompt
    assert "計画名や目標年度から推測" in prompt
