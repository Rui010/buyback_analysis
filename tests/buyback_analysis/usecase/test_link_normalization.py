import pytest

from buyback_analysis.usecase.link_normalization import normalize_date, normalize_method


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-1-2", "2026-01-02"),
        ("2026/01/02", "2026-01-02"),
        ("2026年1月2日", "2026-01-02"),
        (" 2026.01.02 ", "2026-01-02"),
        ("2026-10-13T15:00:00+09:00", "2026-10-13"),
        ("2026-10-13 15:00:00", "2026-10-13"),
        (None, None),
    ],
)
def test_normalize_date(value, expected):
    assert normalize_date(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("市場買付", "market_purchase"),
        ("東京証券取引所における市場買付", "market_purchase"),
        ("discretionary_market_purchase", "market_purchase"),
        ("ToSTNeT-３", "tostnet-3"),
        ("自己株式立会外買付取引（ToSTNeT-3）", "tostnet-3"),
        ("相対取引", "relative_acquisition"),
        (None, None),
    ],
)
def test_normalize_method(value, expected):
    assert normalize_method(value) == expected
