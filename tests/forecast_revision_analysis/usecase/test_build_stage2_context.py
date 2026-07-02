from forecast_revision_analysis.usecase.build_stage2_context import build_stage2_context


def _stage1_obj(periods=None, prev_forecast_date="2026-02-13", reason_raw="修正理由の原文"):
    return {
        "type": "FORECAST_REVISION",
        "data": {
            "prev_forecast_date": prev_forecast_date,
            "value_unit": "百万円",
            "periods": periods if periods is not None else [],
            "reason_raw": reason_raw,
        },
    }


class TestBuildStage2Context:

    def test_includes_company_and_title(self):
        context = build_stage2_context(_stage1_obj(), title="業績予想の修正に関するお知らせ", code="5803", name="フジクラ")
        assert "【企業】フジクラ（5803）" in context
        assert "【タイトル】業績予想の修正に関するお知らせ" in context

    def test_includes_prev_forecast_date(self):
        context = build_stage2_context(_stage1_obj(prev_forecast_date="2026-02-13"), title="t", code="5803", name="n")
        assert "【前回予想公表日】2026-02-13" in context

    def test_prev_forecast_date_none_shows_unknown(self):
        context = build_stage2_context(_stage1_obj(prev_forecast_date=None), title="t", code="5803", name="n")
        assert "【前回予想公表日】不明" in context

    def test_includes_reason_raw(self):
        context = build_stage2_context(_stage1_obj(reason_raw="想定外の受注増加"), title="t", code="5803", name="n")
        assert "【修正理由（原文）】" in context
        assert "想定外の受注増加" in context

    def test_reason_raw_none_shows_placeholder(self):
        context = build_stage2_context(_stage1_obj(reason_raw=None), title="t", code="5803", name="n")
        assert "（記載なし）" in context

    def test_modified_period_included_with_change_pct(self):
        periods = [
            {
                "period_type": "4q", "fiscal_year": 2026, "consolidation_type": "consolidated",
                "metric_name": "sales", "label_raw": "売上高",
                "prev_value": 594000.0, "curr_value": 778000.0,
            }
        ]
        context = build_stage2_context(_stage1_obj(periods=periods), title="t", code="5803", name="n")
        assert "売上高" in context
        assert "連結" in context
        assert "2026年度" in context
        assert "通期" in context
        assert "594,000" in context
        assert "778,000" in context
        assert "+26.8%" in context

    def test_unmodified_period_excluded(self):
        """prev_value == curr_value の期間は【修正内容】に含めない"""
        periods = [
            {
                "period_type": "4q", "metric_name": "sales", "label_raw": "売上高",
                "prev_value": 594000.0, "curr_value": 594000.0,
            }
        ]
        context = build_stage2_context(_stage1_obj(periods=periods), title="t", code="5803", name="n")
        assert "594,000" not in context
        assert "（修正された指標なし）" in context

    def test_no_periods_shows_no_change_placeholder(self):
        context = build_stage2_context(_stage1_obj(periods=[]), title="t", code="5803", name="n")
        assert "（修正された指標なし）" in context

    def test_net_income_total_uses_dedicated_label(self):
        """net_income_total（IFRS非支配持分含む合計）はnet_incomeと別のラベルで表示される"""
        periods = [
            {
                "period_type": "4q", "fiscal_year": 2026, "consolidation_type": "consolidated",
                "metric_name": "net_income_total", "label_raw": "当期利益",
                "prev_value": 548000.0, "curr_value": 470000.0,
            },
            {
                "period_type": "4q", "fiscal_year": 2026, "consolidation_type": "consolidated",
                "metric_name": "net_income", "label_raw": "親会社の所有者に帰属する当期利益",
                "prev_value": 497000.0, "curr_value": 420000.0,
            },
        ]
        context = build_stage2_context(_stage1_obj(periods=periods), title="t", code="6902", name="n")
        assert "当期利益（非支配持分含む合計）" in context
        assert "当期純利益（親会社帰属分）" in context

    def test_unknown_metric_name_falls_back_to_label_raw(self):
        periods = [
            {
                "period_type": "4q", "metric_name": "custom_metric", "label_raw": "独自指標",
                "prev_value": 100.0, "curr_value": 200.0,
            }
        ]
        context = build_stage2_context(_stage1_obj(periods=periods), title="t", code="5803", name="n")
        assert "独自指標" in context

    def test_missing_value_shows_unknown(self):
        periods = [
            {
                "period_type": "4q", "metric_name": "eps", "label_raw": "EPS",
                "prev_value": None, "curr_value": 50.0,
            }
        ]
        context = build_stage2_context(_stage1_obj(periods=periods), title="t", code="5803", name="n")
        assert "不明 → 50" in context
