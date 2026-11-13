"""レビュー用JSON（review_duplicate_candidates.py）で直した中計の結果を検証し、新しい版として採用する。

取込みの前に次をすべて確かめ、1つでも満たさないURLは書き込まない（現行行・既存versionはそのまま）。

1. 前提: 現行のmidterm_plans行があり、code・採用version ID・source hashがレビュー用JSONを作った時点と同じ
   （JSONの作成後に再抽出・再取込みがあれば別の版が採用されているので拒否する。同じJSONの二重取込みも防ぐ）
2. schema・値・期末: 項目の型と許可値、bound=rangeの上限、期末の形式（YYYY/MM）と期間ラベルとの矛盾
3. 正規化: normalize_midterm_resultを通す（明確な完全重複はここで自動統合される）
4. 重複: 正規化後に再検出した重複候補が、すべてレビュー用JSONでresolution=distinctになっている
5. 変更: 正規化後の結果が現行と同じなら取り込まない（同じ内容の版を増やさない）

採用はimport_verified_result（adopt_result）を通すため、新しい版はorigin=unrecordedで追記される。
"""

import re

from midterm_plan_analysis.models.midterm_plan import MidtermPlan
from midterm_plan_analysis.usecase.detect_duplicate_candidates import (
    CANDIDATE_KIND,
    find_possible_duplicate_targets,
    possible_fiscal_end_years,
)
from midterm_plan_analysis.usecase.import_verified_result import import_verified_result
from midterm_plan_analysis.usecase.normalize_midterm_metrics import (
    BOUNDS,
    CONSOLIDATION_LABELS,
    REFERENCE_KINDS,
    REVISION_ROLES,
    TARGET_SCOPES,
    normalize_midterm_result,
)
from midterm_plan_analysis.usecase.post_midterm_plan import VALID_EXTRACTION_STATUSES
from midterm_plan_analysis.usecase.review_duplicate_candidates import current_review_state, plan_result

REQUIRED_ENTRY_KEYS = ("url", "code", "extraction_status", "adopted_version_id", "source_hash", "result", "candidates")
RESOLUTIONS = {None, "merged", "distinct"}
PLAN_YEAR_FIELDS = ("plan_start_year", "plan_end_year")
PLAN_FISCAL_END_FIELDS = ("plan_start_fiscal_end", "plan_end_fiscal_end")
_FISCAL_END = re.compile(r"^\d{4}/(0[1-9]|1[0-2])$")


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _optional(check):
    return lambda value: value is None or check(value)


def _is_text(value) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _is_fiscal_end(value) -> bool:
    return isinstance(value, str) and _FISCAL_END.match(value) is not None


_METRIC_CHECKS = {
    "name": (_is_text, "空でない文字列"),
    "value": (_optional(_is_number), "数値かnull"),
    "value_upper": (_optional(_is_number), "数値かnull"),
    "unit": (_optional(lambda v: isinstance(v, str)), "文字列かnull"),
    "value_text": (_optional(lambda v: isinstance(v, str)), "文字列かnull"),
    "target_year": (_optional(_is_int), "整数かnull"),
    "target_period_label": (_optional(lambda v: isinstance(v, str)), "文字列かnull"),
    "target_fiscal_end": (_optional(_is_fiscal_end), "YYYY/MMかnull"),
    "target_scope": (lambda v: v in TARGET_SCOPES, f"{sorted(TARGET_SCOPES)}のいずれか"),
    "revision_role": (lambda v: v in REVISION_ROLES, f"{sorted(REVISION_ROLES)}のいずれか"),
    "consolidation_label": (_optional(lambda v: v in CONSOLIDATION_LABELS), f"{sorted(CONSOLIDATION_LABELS)}かnull"),
    "bound": (_optional(lambda v: v in BOUNDS), f"{sorted(BOUNDS)}かnull"),
    "page": (_optional(lambda v: _is_int(v) and v >= 1), "1以上の整数かnull"),
}
_REFERENCE_CHECKS = {
    "name": (_is_text, "空でない文字列"),
    "value": (_optional(_is_number), "数値かnull"),
    "unit": (_optional(lambda v: isinstance(v, str)), "文字列かnull"),
    "kind": (lambda v: v in REFERENCE_KINDS, f"{sorted(REFERENCE_KINDS)}のいずれか"),
    "period_label": (_optional(lambda v: isinstance(v, str)), "文字列かnull"),
    "period_fiscal_end": (_optional(_is_fiscal_end), "YYYY/MMかnull"),
    "consolidation_label": (_optional(lambda v: v in CONSOLIDATION_LABELS), f"{sorted(CONSOLIDATION_LABELS)}かnull"),
    "page": (_optional(lambda v: _is_int(v) and v >= 1), "1以上の整数かnull"),
}


def _check_fields(item, checks, where: str) -> list[str]:
    if not isinstance(item, dict):
        return [f"{where}: オブジェクトではありません"]
    errors = [f"{where}.{field}: {expected}である必要があります（{item.get(field)!r}）"
              for field, (check, expected) in checks.items() if not check(item.get(field))]
    if "segment" in item and not _is_text(item["segment"]):
        errors.append(f"{where}.segment: 空でない文字列である必要があります（不要なら項目ごと削除）")
    return errors


def _check_metric_values(item: dict, where: str) -> list[str]:
    errors = []
    value, upper = item.get("value"), item.get("value_upper")
    if item.get("bound") == "range":
        if not _is_number(upper) or (_is_number(value) and upper <= value):
            errors.append(f"{where}.value_upper: bound=rangeでは値（下限）より大きい数値が必要です（{upper!r}）")
    elif upper is not None:
        errors.append(f"{where}.value_upper: bound=range以外ではnullにしてください（{upper!r}）")
    fiscal_end = item.get("target_fiscal_end")
    label_years = possible_fiscal_end_years({"target_period_label": item.get("target_period_label")})
    if _is_fiscal_end(fiscal_end) and label_years is not None and int(fiscal_end[:4]) not in label_years:
        errors.append(f"{where}.target_fiscal_end: 期間ラベル「{item.get('target_period_label')}」と矛盾します"
                      f"（{fiscal_end}）")
    return errors


def validate_reviewed_result(result) -> list[str]:
    """resultのschema・値・期末を検査し、問題の一覧を返す（問題がなければ空）。"""
    if not isinstance(result, dict) or not isinstance(result.get("data"), dict):
        return ["result: {\"type\", \"data\"}の形ではありません"]
    data = result["data"]
    errors = []
    for field in PLAN_YEAR_FIELDS:
        if not _optional(_is_int)(data.get(field)):
            errors.append(f"data.{field}: 整数かnullである必要があります（{data.get(field)!r}）")
    for field in PLAN_FISCAL_END_FIELDS:
        if not _optional(_is_fiscal_end)(data.get(field)):
            errors.append(f"data.{field}: YYYY/MMかnullである必要があります（{data.get(field)!r}）")

    metrics = data.get("metrics")
    if not isinstance(metrics, list):
        errors.append("data.metrics: 配列である必要があります")
    else:
        for i, item in enumerate(metrics):
            where = f"metrics[{i}]"
            item_errors = _check_fields(item, _METRIC_CHECKS, where)
            errors.extend(item_errors or _check_metric_values(item, where))

    references = data.get("reference_values")
    if references is not None and not isinstance(references, list):
        errors.append("data.reference_values: 配列かnullである必要があります")
    elif references:
        for i, item in enumerate(references):
            errors.extend(_check_fields(item, _REFERENCE_CHECKS, f"reference_values[{i}]"))
    return errors


def _check_entry(session, entry) -> tuple[MidtermPlan | None, list[str]]:
    if not isinstance(entry, dict):
        return None, ["entry: オブジェクトではありません"]
    missing = [key for key in REQUIRED_ENTRY_KEYS if key not in entry]
    if missing:
        return None, [f"entry: 必要な項目がありません: {', '.join(missing)}"]
    errors = []
    status = entry["extraction_status"]
    if status not in VALID_EXTRACTION_STATUSES or status == "failed":
        errors.append(f"extraction_status: failed以外の許可値である必要があります（{status!r}）")
    candidates = entry["candidates"]
    if not isinstance(candidates, list):
        errors.append("candidates: 配列である必要があります")
    else:
        for i, candidate in enumerate(candidates):
            if not isinstance(candidate, dict) or candidate.get("resolution") not in RESOLUTIONS:
                resolution = candidate.get("resolution") if isinstance(candidate, dict) else candidate
                errors.append(f"candidates[{i}].resolution: merged・distinct・nullのいずれかにしてください"
                              f"（{resolution!r}）")

    current = session.query(MidtermPlan).filter(MidtermPlan.url == entry["url"]).one_or_none()
    if current is None:
        errors.append("現行のmidterm_plans行がありません")
        return None, errors
    if current.code != entry["code"]:
        errors.append(f"code: 現行行と違います（現行={current.code} JSON={entry['code']}）")
    state = current_review_state(session, entry["url"])
    for key in ("adopted_version_id", "source_hash"):
        if state[key] != entry[key]:
            errors.append(f"{key}: レビュー用JSONの作成後に変わっています（現在={state[key]} JSON={entry[key]}）")
    return current, errors


def _distinct_ids(candidates) -> set[str]:
    return {c.get("candidate_id") for c in candidates if isinstance(c, dict) and c.get("resolution") == "distinct"}


def prepare_reviewed_entry(session, entry) -> tuple[dict | None, list[str]]:
    """entryを検証し、(採用する正規化後のresult, 問題の一覧)を返す。問題があればresultはNone。書き込まない。"""
    current, errors = _check_entry(session, entry)
    if current is None:
        return None, errors
    errors.extend(validate_reviewed_result(entry["result"]))
    if errors:
        return None, errors

    context = f"{entry['code']} - {entry['url']}"
    normalized = normalize_midterm_result(entry["result"], page_available=True, log_context=context)
    distinct = _distinct_ids(entry["candidates"])
    for candidate in find_possible_duplicate_targets(normalized["data"]["metrics"]):
        if candidate["candidate_id"] not in distinct:
            errors.append(f"{CANDIDATE_KIND}が残っています（resolution=distinctではない）: "
                          f"candidate_id={candidate['candidate_id']} metrics{candidate['metric_indexes']} "
                          f"{candidate['detail']}")
    if errors:
        return None, errors

    current_result = plan_result(current)
    if current_result is not None and entry["extraction_status"] == current.extraction_status:
        current_normalized = normalize_midterm_result(current_result, page_available=True, log_context=context)
        if current_normalized["data"] == normalized["data"]:
            return None, ["変更なし: 現行の採用版と同じ内容のため取り込みません"]
    return normalized, []


def import_reviewed_entry(session, entry, **kwargs) -> tuple[bool, list[str]]:
    """検証を通ったentryだけを新しい版として採用する。(採用したか, 問題の一覧)を返す。"""
    result, errors = prepare_reviewed_entry(session, entry)
    if result is None:
        return False, errors
    adopted = import_verified_result(
        session, url=entry["url"], result=result, extraction_status=entry["extraction_status"], **kwargs,
    )
    return adopted, [] if adopted else ["採用切替に失敗しました（旧採用を維持）"]
