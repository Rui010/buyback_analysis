from typing import Any, Dict

from forecast_revision_analysis.usecase.post_forecast_revision import _calc_change_pct, _to_float

_METRIC_NAME_LABELS = {
    "sales": "売上高",
    "bussiness_income": "営業利益",
    "ordinary_income": "経常利益",
    "net_income": "当期純利益（親会社帰属分）",
    "net_income_total": "当期利益（非支配持分含む合計）",
    "ebitda": "EBITDA",
    "eps": "EPS",
    "dividend_per_share": "1株当たり配当",
}

_PERIOD_TYPE_LABELS = {
    "1q": "第1四半期",
    "2q": "第2四半期",
    "3q": "第3四半期",
    "4q": "通期",
}

_CONSOLIDATION_TYPE_LABELS = {
    "consolidated": "連結",
    "non_consolidated": "単体",
}


def _format_value(v: float | None) -> str:
    if v is None:
        return "不明"
    return f"{v:,.0f}"


def _format_period_line(period: Dict[str, Any]) -> str:
    prev = _to_float(period.get("prev_value"))
    curr = _to_float(period.get("curr_value"))

    label = _METRIC_NAME_LABELS.get(period.get("metric_name"), period.get("label_raw") or period.get("metric_name"))
    consolidation = _CONSOLIDATION_TYPE_LABELS.get(period.get("consolidation_type"), "")
    period_label = _PERIOD_TYPE_LABELS.get(period.get("period_type"), period.get("period_type"))
    fiscal_year = period.get("fiscal_year")

    scope_parts = [p for p in [consolidation, f"{fiscal_year}年度" if fiscal_year else None, period_label] if p]
    scope = "・".join(scope_parts)

    pct = _calc_change_pct(prev, curr)
    pct_str = f"（{pct:+.1f}%）" if pct is not None else ""

    return f"- {label}（{scope}）: {_format_value(prev)} → {_format_value(curr)}{pct_str}"


def build_stage2_context(stage1_obj: Dict[str, Any], title: str, code: str, name: str) -> str:
    """
    Stage1の抽出結果からStage2（推論）用の要約テキストを機械的に整形する。

    PDF本文は含めず、修正があった期間（is_modified相当）の一覧とreason_rawのみで構成する。
    """
    inner = stage1_obj.get("data", {})

    modified_periods = [
        p for p in inner.get("periods", [])
        if _to_float(p.get("prev_value")) != _to_float(p.get("curr_value"))
    ]

    lines = [
        f"【企業】{name}（{code}）",
        f"【タイトル】{title}",
        f"【前回予想公表日】{inner.get('prev_forecast_date') or '不明'}",
        "【修正内容】",
    ]
    if modified_periods:
        lines.extend(_format_period_line(p) for p in modified_periods)
    else:
        lines.append("（修正された指標なし）")

    lines.append("【修正理由（原文）】")
    lines.append(inner.get("reason_raw") or "（記載なし）")

    return "\n".join(lines)
