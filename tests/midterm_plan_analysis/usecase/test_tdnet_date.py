import datetime

import pandas as pd
import pytest

from midterm_plan_analysis.usecase.tdnet_date import disclosure_date_str, pdf_folder_str

JST = datetime.timezone(datetime.timedelta(hours=9))


@pytest.mark.parametrize("value", [
    pd.Timestamp("2025-04-09 00:00:00"),         # PostgreSQLのtimestamp without time zone（pandasで読んだ値）
    datetime.datetime(2025, 4, 9, 0, 0),
    datetime.datetime(2025, 4, 9, 23, 59),
    datetime.date(2025, 4, 9),
])
def test_naive_value_keeps_its_own_date(value):
    assert disclosure_date_str(value) == "2025-04-09"
    assert pdf_folder_str(value) == "20250409"


def test_aware_utc_value_is_converted_to_jst_date():
    # JSTの0時をUTCで表した値（前日15:00Z）の日付部分を使うと1日早くなる（2026-11-11に16件で起きた）
    value = datetime.datetime(2025, 4, 8, 15, 0, tzinfo=datetime.timezone.utc)
    assert disclosure_date_str(value) == "2025-04-09"
    assert pdf_folder_str(value) == "20250409"


def test_aware_jst_value_keeps_its_date():
    value = pd.Timestamp("2025-04-09 00:00:00", tz=JST)
    assert disclosure_date_str(value) == "2025-04-09"


def test_string_is_rejected():
    with pytest.raises(TypeError):
        disclosure_date_str("2025-04-08T15:00:00.000Z")
