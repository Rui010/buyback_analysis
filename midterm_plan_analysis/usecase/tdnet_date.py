"""tdnet.date（PostgreSQLのtimestamp without time zone、日本時間の日付）から、
midterm_plans.disclosure_date（"YYYY-MM-DD"）とPDFの保存フォルダ名（"YYYYMMDD"）を作る。

naiveな値はそのまま日本時間の日付とみなす。タイムゾーン付きの値は日本時間に直してから日付を取る
（JSTの0時をUTCで表した「前日15:00Z」の日付部分を使うと1日早くなるため。2026-11-11に16件で起きた）。
文字列は受け付けない（ISO文字列の日付部分を切り出す使い方を防ぐ）。
"""

import datetime

JST = datetime.timezone(datetime.timedelta(hours=9))


def _jst_date(value) -> datetime.date:
    if isinstance(value, datetime.datetime):  # pandas.Timestampも含む
        if value.tzinfo is not None:
            value = value.astimezone(JST)
        return value.date()
    if isinstance(value, datetime.date):
        return value
    raise TypeError(f"tdnet.dateにはdatetimeかdateを渡してください: {value!r}")


def disclosure_date_str(value) -> str:
    """"YYYY-MM-DD"（midterm_plans.disclosure_date）。"""
    return _jst_date(value).strftime("%Y-%m-%d")


def pdf_folder_str(value) -> str:
    """"YYYYMMDD"（PDFの保存フォルダ名・pud_date_str）。"""
    return _jst_date(value).strftime("%Y%m%d")
