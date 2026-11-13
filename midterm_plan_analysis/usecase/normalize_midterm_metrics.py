"""中計のmetrics抽出結果（metrics・reference_values）の正規化。

LLMの出力を引継ぎ仕様（ir-analytics-platform docs/plans/handoffs/buyback-midterm-target-extraction.md
第4節・第7節）の形にそろえる。中計は汎用の解析関数を使いresponseSchemaがないため、
欠けた項目はnull・unknownで補い、失敗扱いにはしない。

- value: 数値かnull。文字列は数値に直せるときだけ直し、元の表記をvalue_textに残す
- target_scope・revision_role・consolidation_label・bound・kind: 許可値以外はunknown・current・null
- page: 1以上の整数。LLMがページの境目を見られない入力（page_available=False）では常にnull
- reference_values: 配列でなければ空配列
- metricsの重複: 指標名・値・単位・segment・連結区分・見直し前後・bound・上限・期末（null以外）が同じ行は、
  別ページの同じ目標として最初の1行だけ残す（5367で「2031年3月期」「2030年度」の2行になった対策）。
  期末か値がnullの行は同じ期・同じ値か判断できないので残す
- 重複候補: 自動でまとめられないが同じ期の同じ目標かもしれない行の組（detect_duplicate_candidates.py）は
  残したまま[REVIEW]ログを出す。レビュー用JSONは scripts/review_midterm_duplicate_candidates.py で出す
  （ログは出力を変えないのでNORMALIZER_VERSIONに含めない）

正規化の規則を変えたら NORMALIZER_VERSION を上げること（metrics stageのextractor_versionに含まれる）。
"""

import copy
import re
import unicodedata

from buyback_analysis.interface.logger import Logger
from midterm_plan_analysis.usecase.detect_duplicate_candidates import find_possible_duplicate_targets

logger = Logger()

NORMALIZER_VERSION = "midterm_metrics_normalizer:2"

TARGET_SCOPES = {"plan_final", "plan_interim", "long_term", "cumulative", "unknown"}
# 計画期間を基準に決める種類（計画期間が分からない文書ではunknownにする。cumulativeは期間に依らない）
PLAN_RELATIVE_SCOPES = {"plan_final", "plan_interim", "long_term"}
REVISION_ROLES = {"current", "previous"}
CONSOLIDATION_LABELS = {"consolidated", "non_consolidated"}
CONSOLIDATION_ALIASES = {"連結": "consolidated", "単体": "non_consolidated", "個別": "non_consolidated"}
BOUNDS = {"exact", "lower", "upper", "approx", "range"}
REFERENCE_KINDS = {"actual", "estimate", "forecast", "unknown"}
REFERENCE_KIND_ALIASES = {"実績": "actual", "見込": "estimate", "見込み": "estimate", "予想": "forecast"}

PLAN_END_FIELDS = ("plan_end_year", "plan_end_period_label", "plan_end_fiscal_end")

_NUMBER = r"-?\d+(?:\.\d+)?"
_UNIT = r"(?:億円|百万円|千円|万円|円|%|倍|pt|ポイント|人|件|店|社|台|t|ドル)?"
_SINGLE = re.compile(rf"^(約)?({_NUMBER}){_UNIT}(以上|以下|未満|程度)?$")
_RANGE = re.compile(rf"^(約)?({_NUMBER}){_UNIT}[〜~]({_NUMBER}){_UNIT}(程度)?$")
_QUALIFIER_BOUNDS = {"以上": "lower", "以下": "upper", "未満": "upper", "程度": "approx"}


def _clean_number_text(text: str) -> str:
    """全角→半角（NFKC）、三角記号・マイナス記号→'-'、桁区切りと空白の除去。"""
    text = unicodedata.normalize("NFKC", text)
    for minus in ("△", "▲", "−", "‐", "－"):
        text = text.replace(minus, "-")
    return re.sub(r"[,\s]", "", text)


def _to_number(text: str):
    return float(text) if "." in text else int(text)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def parse_number(raw):
    """数値または数値だけの文字列を数値にする。それ以外（範囲・「以上」付き・語句）はNone。"""
    if _is_number(raw):
        return raw
    if not isinstance(raw, str):
        return None
    text = _clean_number_text(raw)
    if not re.fullmatch(_NUMBER, text):
        return None
    return _to_number(text)


def _parse_qualified(raw: str):
    """「7.0以上」「約100」「5〜7」を (下限または値, 上限, bound) にする。読めなければNone。"""
    text = _clean_number_text(raw)
    match = _RANGE.fullmatch(text)
    if match:
        return _to_number(match.group(2)), _to_number(match.group(3)), "range"
    match = _SINGLE.fullmatch(text)
    if match:
        approx, number, qualifier = match.groups()
        bound = _QUALIFIER_BOUNDS[qualifier] if qualifier else ("approx" if approx else "exact")
        return _to_number(number), None, bound
    return None


def _text_or_none(value):
    if isinstance(value, str) and value.strip():
        return value
    return None


def _normalize_value_fields(item: dict) -> None:
    """value・value_text・bound・value_upperをそろえる（itemを書き換える）。"""
    raw_value = item.get("value")
    value_text = _text_or_none(item.get("value_text"))
    if isinstance(raw_value, str) and value_text is None:
        value_text = raw_value if raw_value.strip() else None

    value, upper_from_text, derived_bound = None, None, None
    if _is_number(raw_value):
        value = raw_value
    elif isinstance(raw_value, str):
        value = parse_number(raw_value)
    qualified = _parse_qualified(value_text) if value_text is not None else None
    if qualified is not None:
        qualified_value, upper_from_text, derived_bound = qualified
        if value is None and isinstance(raw_value, str):
            value = qualified_value

    bound = item.get("bound") if item.get("bound") in BOUNDS else derived_bound
    value_upper = None
    if bound == "range":
        value_upper = parse_number(item.get("value_upper"))
        if value_upper is None:
            value_upper = upper_from_text

    item["value"] = value
    item["value_text"] = value_text
    item["bound"] = bound
    item["value_upper"] = value_upper


def _normalize_page(raw, page_available: bool):
    if not page_available or isinstance(raw, bool):
        return None
    if isinstance(raw, float):
        raw = int(raw) if raw.is_integer() else None
    elif isinstance(raw, str):
        text = unicodedata.normalize("NFKC", raw).strip()
        raw = int(text) if text.isdigit() else None
    return raw if isinstance(raw, int) and raw >= 1 else None


def _normalize_consolidation(raw):
    if raw in CONSOLIDATION_LABELS:
        return raw
    return CONSOLIDATION_ALIASES.get(raw.strip()) if isinstance(raw, str) else None


def _normalize_segment(item: dict) -> None:
    if "segment" in item and _text_or_none(item["segment"]) is None:
        del item["segment"]


def _normalize_common(item: dict, page_available: bool) -> None:
    _normalize_value_fields(item)
    item.setdefault("unit", None)
    item["consolidation_label"] = _normalize_consolidation(item.get("consolidation_label"))
    item["page"] = _normalize_page(item.get("page"), page_available)
    _normalize_segment(item)


def _normalize_metric(item: dict, *, page_available: bool, plan_period_known: bool) -> dict:
    item = dict(item)
    _normalize_common(item, page_available)
    scope = item.get("target_scope")
    if scope not in TARGET_SCOPES:
        scope = "unknown"
    if scope in PLAN_RELATIVE_SCOPES and not plan_period_known:
        scope = "unknown"
    item["target_scope"] = scope
    if item.get("revision_role") not in REVISION_ROLES:
        item["revision_role"] = "current"
    return item


def _normalize_reference(item: dict, *, page_available: bool) -> dict:
    item = dict(item)
    _normalize_common(item, page_available)
    # 参考値は上下限を持たない（範囲・以上はvalue_textに残る）
    item.pop("bound", None)
    item.pop("value_upper", None)
    kind = item.get("kind")
    if kind not in REFERENCE_KINDS:
        kind = REFERENCE_KIND_ALIASES.get(kind.strip(), "unknown") if isinstance(kind, str) else "unknown"
    item["kind"] = kind
    item.setdefault("period_label", None)
    item.setdefault("period_fiscal_end", None)
    return item


def _dicts(items) -> list[dict]:
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _duplicate_key(item: dict, period_field: str):
    return (
        item.get("name"), item.get("value"), item.get("unit"), item.get("segment"),
        item.get("consolidation_label"), item.get(period_field),
    )


def _same_target_key(item: dict):
    if item.get("value") is None or item.get("target_fiscal_end") is None:
        return None
    return (
        item.get("name"), item.get("value"), item.get("unit"), item.get("segment"),
        item.get("consolidation_label"), item.get("revision_role"), item.get("bound"),
        item.get("value_upper"), item.get("target_fiscal_end"),
    )


def _merge_duplicate_metrics(metrics: list[dict], log_context: str) -> list[dict]:
    seen, merged = set(), []
    for item in metrics:
        key = _same_target_key(item)
        if key is not None and key in seen:
            logger.info(
                f"[NORMALIZE] 同じ目標の重複を1行にまとめました: name={item.get('name')} value={item.get('value')} "
                f"fiscal_end={item.get('target_fiscal_end')} label={item.get('target_period_label')} "
                f"page={item.get('page')} {log_context}"
            )
            continue
        if key is not None:
            seen.add(key)
        merged.append(item)
    return merged


def _warn_duplicates(metrics: list[dict], references: list[dict], log_context: str) -> None:
    target_keys = {_duplicate_key(m, "target_period_label") for m in metrics if m.get("value") is not None}
    for ref in references:
        if ref.get("value") is not None and _duplicate_key(ref, "period_label") in target_keys:
            logger.info(
                f"[WARNING] 同じ値がmetricsとreference_valuesの両方にあります: "
                f"name={ref.get('name')} value={ref.get('value')} period={ref.get('period_label')} {log_context}"
            )


def _log_possible_duplicates(metrics: list[dict], log_context: str) -> None:
    for candidate in find_possible_duplicate_targets(metrics):
        logger.info(
            f"[REVIEW] {candidate['kind']}（自動では削除しません）: {candidate['detail']} "
            f"reasons={','.join(candidate['reasons'])} {log_context}"
        )


def normalize_midterm_result(result, *, page_available: bool, log_context: str = ""):
    """metrics抽出のLLM結果（{"type", "data"}）を正規化した新しい辞書を返す。Noneはそのまま返す。"""
    if not isinstance(result, dict):
        return result
    result = copy.deepcopy(result)
    data = result.get("data")
    if not isinstance(data, dict):
        return result

    plan_period_known = any(data.get(field) not in (None, "") for field in PLAN_END_FIELDS)
    metrics = data.get("metrics")
    if metrics is not None:
        data["metrics"] = _merge_duplicate_metrics([
            _normalize_metric(m, page_available=page_available, plan_period_known=plan_period_known)
            for m in _dicts(metrics)
        ], log_context)
    data["reference_values"] = [
        _normalize_reference(r, page_available=page_available) for r in _dicts(data.get("reference_values"))
    ]
    _warn_duplicates(data.get("metrics") or [], data["reference_values"], log_context)
    _log_possible_duplicates(data.get("metrics") or [], log_context)
    return result
