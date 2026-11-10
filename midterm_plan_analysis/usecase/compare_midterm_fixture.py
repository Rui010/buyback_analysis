"""中計の抽出結果と、ir-analytics-platformの原典確認の正解データ（midterm-source-review.json）の突き合わせ。

引継ぎ仕様（docs/plans/handoffs/buyback-midterm-target-extraction.md）第8節の受入条件1〜8を
文書ごとに判定する。正解データは全社の売上高・営業利益・事業利益だけを持つため、
抽出結果もこの3指標の全社値（segmentなし）だけを比べる。

期末は正解データのperiod_end（"2026-03-31"）と抽出結果の"YYYY/MM"を年月で比べる。
抽出結果の期末がnullのときは「判断できない」として値だけで照合する（条件1の「判断できる場合」）。
"""

import math
import re
import unicodedata

UNIT_FACTORS = {"億円": 1e8, "百万円": 1e6, "千万円": 1e7, "万円": 1e4, "千円": 1e3, "円": 1}
RAW_UNIT_FACTORS = {"oku_yen": 1e8, "million_yen": 1e6}
TARGET_KINDS = {"plan_target": "current", "previous_target": "previous"}
REFERENCE_KINDS = {"actual": "actual", "estimate": "estimate", "company_forecast": "forecast"}
# 正解データのうち、抽出結果のmetricsに入ってはいけない値
NON_TARGET_KINDS = set(REFERENCE_KINDS)

_EXCLUDED_NAME_PARTS = ("率", "比", "成長", "CAGR", "増減", "伸び", "シェア", "構成")


def metric_code(name) -> str | None:
    """指標名を正解データのmetric_code（revenue / operating_profit / business_profit）に寄せる。"""
    if not isinstance(name, str):
        return None
    name = re.sub(r"\s", "", unicodedata.normalize("NFKC", name))
    if any(part in name for part in _EXCLUDED_NAME_PARTS):
        return None
    if "事業利益" in name:
        return "business_profit"
    if "営業利益" in name:
        return "operating_profit"
    if any(word in name for word in ("売上高", "売上収益", "営業収益")):
        return "revenue"
    return None


def fiscal_end(period_end: str | None) -> str | None:
    """"2026-03-31" → "2026/03"。"""
    if not period_end:
        return None
    year, month = period_end.split("-")[:2]
    return f"{year}/{month}"


def to_yen(value, unit) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    factor = UNIT_FACTORS.get(unicodedata.normalize("NFKC", unit).strip()) if isinstance(unit, str) else None
    return None if factor is None else value * factor


def _company_items(items, code):
    return [item for item in items or [] if metric_code(item.get("name")) == code]


def _label_year(item, label_field):
    """期末がnullのときの照合用に、target_year、なければ期間表記の最初の4桁の年を返す。"""
    year = item.get("target_year")
    if isinstance(year, int) and not isinstance(year, bool):
        return year
    match = re.search(r"(\d{4})", unicodedata.normalize("NFKC", item.get(label_field) or ""))
    return int(match.group(1)) if match else None


def _find(items, *, code, yen, expected_fiscal, fiscal_field, label_field, role=None, used=()):
    """同じ指標・同じ値の候補から、(状態, 項目)を返す。

    状態: ok（期末一致）/ period_unknown（抽出側の期末がnullで、表記の年が矛盾しない）/
    period_mismatch / segment_attached / missing。
    期末がnullの候補は、表記の年が期末の年かその前年（「2027年度」→2028/03）なら一致とみなす。
    roleを指定すると、revision_roleが一致する候補を優先する。usedの項目（照合済み）は後回しにする。
    """
    expected_year = int(expected_fiscal[:4])
    same_value = [
        item for item in _company_items(items, code)
        if (v := to_yen(item.get("value"), item.get("unit"))) is not None and math.isclose(v, yen, rel_tol=1e-9)
    ]

    def period_status(item):
        fiscal = item.get(fiscal_field)
        if fiscal == expected_fiscal:
            return "ok"
        if fiscal is None:
            year = _label_year(item, label_field)
            if year is None or year in (expected_year, expected_year - 1):
                return "period_unknown"
        return "period_mismatch"

    rank = {"ok": 0, "period_unknown": 1, "period_mismatch": 2}
    company = sorted(
        (item for item in same_value if not item.get("segment")),
        key=lambda item: (
            rank[period_status(item)],
            role is not None and item.get("revision_role") != role,
            id(item) in used,
        ),
    )
    if company:
        return period_status(company[0]), company[0]
    if same_value:
        return "segment_attached", same_value[0]
    return "missing", None


def _label(value: dict) -> str:
    consolidation = value.get("consolidation")
    suffix = f" {consolidation}" if consolidation in ("consolidated", "non_consolidated") else ""
    return f"{value['metric_code']} {value['period_end']} {value['value']}{suffix} ({value['value_kind']})"


def compare_document(doc: dict, result: dict | None, extraction_status: str | None) -> dict:
    """1文書を判定し、条件ごとの {checked, failures: [理由]} と補足情報を返す。"""
    data = (result or {}).get("data") or {}
    metrics = data.get("metrics") or []
    references = data.get("reference_values") or []
    factor = RAW_UNIT_FACTORS.get(doc.get("raw_unit"))
    plan_end = doc.get("plan_period_end")
    conditions = {str(n): {"checked": 0, "failures": []} for n in range(1, 9)}
    notes = []
    matched_ids = set()

    def check(number, ok, reason):
        conditions[number]["checked"] += 1
        if not ok:
            conditions[number]["failures"].append(reason)

    for value in doc.get("values", []):
        kind = value["value_kind"]
        yen = value["value"] * factor
        expected_fiscal = fiscal_end(value["period_end"])
        label = _label(value)

        if kind in TARGET_KINDS:
            status, item = _find(metrics, code=value["metric_code"], yen=yen, expected_fiscal=expected_fiscal,
                                 fiscal_field="target_fiscal_end", label_field="target_period_label",
                                 role=TARGET_KINDS[kind], used=matched_ids)
            if item is not None:
                matched_ids.add(id(item))
            if kind == "plan_target":
                check("1", status in ("ok", "period_unknown"),
                      f"{label}: {status}" + (f" target_fiscal_end={item.get('target_fiscal_end')}" if item else ""))
                if status == "period_unknown":
                    notes.append(f"{label}: target_fiscal_endがnull（値で照合）")
                if plan_end and value["period_end"] > plan_end:
                    check("2", item is not None and item.get("target_scope") == "long_term",
                          f"{label}: target_scope={item.get('target_scope') if item else '（未抽出）'}")
            if kind == "previous_target":
                check("3", item is not None and item.get("revision_role") == "previous",
                      f"{label}: revision_role={item.get('revision_role') if item else '（未抽出）'}")
            elif item is not None and item.get("revision_role") != "current":
                notes.append(f"{label}: revision_role={item.get('revision_role')}")
            if value.get("bound") and item is not None and item.get("bound") != value["bound"]:
                notes.append(f"{label}: bound={item.get('bound')}（正解 {value['bound']}）")
            if doc["security_code"] == "8185" and kind == "plan_target":
                check("6", item is not None and item.get("consolidation_label") == value["consolidation"],
                      f"{label}: consolidation_label={item.get('consolidation_label') if item else '（未抽出）'}")
            if doc["security_code"] in ("1814", "4042"):
                check("7", status != "segment_attached", f"{label}: segment={item.get('segment') if item else None}")
            if item is not None and item.get("page") != value.get("page"):
                notes.append(f"{label}: page={item.get('page')}（正解 {value.get('page')}）")

        if kind in NON_TARGET_KINDS:
            status, item = _find(metrics, code=value["metric_code"], yen=yen, expected_fiscal=expected_fiscal,
                                 fiscal_field="target_fiscal_end", label_field="target_period_label")
            # 期末がnullの同値は混入の疑いとして扱う（目標と偶然同値の可能性もあるため理由に状態を残す）
            check("4", status not in ("ok", "period_unknown"), f"{label}: metricsに混入（{status}）")
            ref_status, ref = _find(references, code=value["metric_code"], yen=yen, expected_fiscal=expected_fiscal,
                                    fiscal_field="period_fiscal_end", label_field="period_label")
            expected_kind = REFERENCE_KINDS[kind]
            check("5", ref_status in ("ok", "period_unknown") and ref.get("kind") == expected_kind,
                  f"{label}: reference_values {ref_status}" + (f" kind={ref.get('kind')}" if ref else ""))

    extras = [
        f"{m.get('name')} {m.get('value')}{m.get('unit') or ''} {m.get('target_fiscal_end')} "
        f"scope={m.get('target_scope')} role={m.get('revision_role')}"
        for m in metrics
        if not m.get("segment") and metric_code(m.get("name")) and id(m) not in matched_ids
    ]

    expected_status = doc.get("db_extraction_status")
    if expected_status in ("withdrawn", "postponed"):
        check("8", extraction_status == expected_status,
              f"extraction_status={extraction_status}（従来 {expected_status}）")
    elif extraction_status != expected_status:
        notes.append(f"extraction_status={extraction_status}（従来 {expected_status}）")

    return {"conditions": conditions, "unmatched_company_metrics": extras, "notes": notes}


def summarize(per_document: list[dict]) -> dict:
    """文書ごとの判定を条件ごとに合算する。"""
    total = {str(n): {"checked": 0, "failed": 0} for n in range(1, 9)}
    for doc in per_document:
        for number, condition in doc["comparison"]["conditions"].items():
            total[number]["checked"] += condition["checked"]
            total[number]["failed"] += len(condition["failures"])
    return total
