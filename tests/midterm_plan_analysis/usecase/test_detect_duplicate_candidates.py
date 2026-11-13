import pytest

from midterm_plan_analysis.usecase.detect_duplicate_candidates import (
    DETECTOR_VERSION,
    candidate_id,
    find_possible_duplicate_targets,
    possible_fiscal_end_years,
)


def _metric(**overrides):
    metric = {
        "name": "売上高", "value": 13000, "unit": "百万円", "target_year": 2031,
        "target_period_label": "2031年3月期（計画）", "target_fiscal_end": "2031/03",
        "target_scope": "plan_final", "revision_role": "current", "consolidation_label": None,
        "bound": "exact", "value_upper": None, "value_text": "13,000", "page": 1,
    }
    metric.update(overrides)
    return metric


def _p10(**overrides):
    """5367のp.10「2030年度」（期末null）の行。"""
    values = {"target_year": 2030, "target_period_label": "2030年度", "target_fiscal_end": None, "page": 10}
    values.update(overrides)
    return _metric(**values)


class TestAcceptance5367:
    def test_sales_and_operating_income_each_become_one_candidate(self):
        metrics = [
            _metric(),
            _metric(name="営業利益", value=1940, value_text="1,940"),
            _metric(name="ROE", value=10, unit="%", bound="lower", value_text="10％以上"),
            _p10(),
            _p10(name="営業利益", value=1940, value_text="1,940"),
            _p10(name="売上高", value=11000, target_year=2027, target_period_label="2027年度",
                 target_scope="plan_interim"),
        ]
        candidates = find_possible_duplicate_targets(metrics)

        pairs = {(c["rows"][0]["name"], c["rows"][0]["value"]): c for c in candidates}
        assert set(pairs) == {("売上高", 13000), ("営業利益", 1940)}
        for candidate in pairs.values():
            assert candidate["kind"] == "possible_duplicate_target"
            labels = [row["target_period_label"] for row in candidate["rows"]]
            assert labels == ["2031年3月期（計画）", "2030年度"]
            assert candidate["pages"] == [1, 10]
            assert "fiscal_end_missing_one_side" in candidate["reasons"]
            assert "period_label_differs" in candidate["reasons"]
            assert candidate["resolution"] is None
        assert pairs[("売上高", 13000)]["metric_indexes"] == [0, 3]
        assert pairs[("営業利益", 1940)]["metric_indexes"] == [1, 4]

    def test_rows_contain_all_fields(self):
        row = _p10(segment="住宅")
        candidate = find_possible_duplicate_targets([_metric(segment="住宅"), row])[0]
        assert candidate["rows"][1] == row

    def test_input_is_not_modified(self):
        metrics = [_metric(), _p10()]
        before = [dict(m) for m in metrics]
        find_possible_duplicate_targets(metrics)
        assert metrics == before


class TestDetection:
    def test_fiscal_ends_one_year_apart_with_fiscal_year_label(self):
        # 「2030年度」を2030/03と読んだ行と、「2031年3月期」の2031/03の行
        candidates = find_possible_duplicate_targets([_metric(), _p10(target_fiscal_end="2030/03")])
        assert len(candidates) == 1
        assert "fiscal_end_differs" in candidates[0]["reasons"]

    def test_both_fiscal_ends_null_with_different_labels(self):
        metrics = [_metric(target_fiscal_end=None), _p10()]
        candidates = find_possible_duplicate_targets(metrics)
        assert candidates[0]["reasons"][0] == "fiscal_end_missing_both"

    def test_same_fiscal_end_with_different_labels_left_unmerged(self):
        # 正規化v2より前に保存された行（v2なら自動統合される）
        candidates = find_possible_duplicate_targets([_metric(), _p10(target_fiscal_end="2031/03")])
        assert candidates[0]["reasons"][0] == "same_fiscal_end_not_merged"

    def test_detail_is_readable(self):
        detail = find_possible_duplicate_targets([_metric(), _p10()])[0]["detail"]
        assert "p.1" in detail and "p.10" in detail and "2030年度" in detail

    @pytest.mark.parametrize("overrides", [
        {"value": 13001},
        {"name": "連結売上高"},
        {"unit": "億円"},
        {"segment": "住宅"},
        {"consolidation_label": "consolidated"},
        {"revision_role": "previous"},
        {"target_scope": "plan_interim"},
        {"bound": "lower"},
    ])
    def test_different_attributes_are_not_candidates(self, overrides):
        assert find_possible_duplicate_targets([_metric(), _p10(**overrides)]) == []

    def test_range_upper_must_match(self):
        metrics = [_metric(bound="range", value_upper=14000), _p10(bound="range", value_upper=15000)]
        assert find_possible_duplicate_targets(metrics) == []

    def test_same_page_is_not_candidate(self):
        assert find_possible_duplicate_targets([_metric(), _p10(page=1)]) == []

    @pytest.mark.parametrize("pages", [(None, 10), (1, None), (None, None)])
    def test_unknown_page_is_not_candidate(self, pages):
        assert find_possible_duplicate_targets([_metric(page=pages[0]), _p10(page=pages[1])]) == []

    def test_null_value_is_not_candidate(self):
        assert find_possible_duplicate_targets([_metric(value=None), _p10(value=None)]) == []

    def test_same_label_and_fiscal_end_both_null_is_not_candidate(self):
        metrics = [_p10(page=3), _p10()]
        assert find_possible_duplicate_targets(metrics) == []

    def test_incompatible_periods_are_not_candidates(self):
        # ROE 10%以上が別の年度に並ぶのは別の目標
        metrics = [
            _metric(target_period_label="2029年3月期", target_fiscal_end="2029/03"),
            _p10(target_period_label="2030年3月期", target_fiscal_end="2030/03"),
        ]
        assert find_possible_duplicate_targets(metrics) == []

    def test_fiscal_year_label_far_from_fiscal_end_is_not_candidate(self):
        assert find_possible_duplicate_targets([_metric(), _p10(target_period_label="2027年度")]) == []

    def test_unparseable_label_is_treated_as_possible(self):
        assert len(find_possible_duplicate_targets([_metric(), _p10(target_period_label="最終年度")])) == 1

    def test_non_dict_items_are_ignored(self):
        assert find_possible_duplicate_targets([_metric(), "x", None, _p10()])[0]["metric_indexes"] == [0, 3]

    def test_none_metrics(self):
        assert find_possible_duplicate_targets(None) == []


class TestPossibleFiscalEndYears:
    @pytest.mark.parametrize("item,expected", [
        ({"target_fiscal_end": "2031/03", "target_period_label": "2031年3月期"}, {2031}),
        ({"target_fiscal_end": None, "target_period_label": "2030年度"}, {2030, 2031}),
        ({"target_fiscal_end": "2030/03", "target_period_label": "2030年度"}, {2030, 2031}),
        ({"target_fiscal_end": None, "target_period_label": "２０３１年３月期"}, {2031}),
        ({"target_fiscal_end": None, "target_period_label": "FY2030"}, {2030, 2031}),
        ({"target_fiscal_end": None, "target_period_label": "2031 年 3 月期"}, {2031}),
        ({"target_fiscal_end": None, "target_period_label": "最終年度"}, None),
        ({"target_fiscal_end": None, "target_period_label": None}, None),
        ({"target_fiscal_end": "不明", "target_period_label": None}, None),
    ])
    def test_years(self, item, expected):
        assert possible_fiscal_end_years(item) == expected


class TestCandidateId:
    def test_same_rows_give_same_id_regardless_of_order_and_index(self):
        a, b = _metric(), _p10()
        first = find_possible_duplicate_targets([a, b])[0]
        second = find_possible_duplicate_targets([_metric(name="X"), b, a])[0]
        assert first["candidate_id"] == second["candidate_id"] == candidate_id(b, a)

    def test_value_text_does_not_change_id(self):
        assert candidate_id(_metric(), _p10()) == candidate_id(_metric(value_text="13000"), _p10())

    def test_different_rows_give_different_id(self):
        assert candidate_id(_metric(), _p10()) != candidate_id(_metric(), _p10(page=11))


def test_detector_version():
    assert DETECTOR_VERSION == "midterm_duplicate_detector:1"
