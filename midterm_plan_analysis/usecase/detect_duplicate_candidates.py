"""中計metricsの重複候補（possible_duplicate_target）の検査。LLMは呼ばない。

normalize_midterm_metrics.pyが自動でまとめるのは、期末（target_fiscal_end）まで同じ明確な重複だけ。
それ以外で「同じ期の同じ目標を別ページから2回取った」可能性がある行の組を候補として返す
（5367でp.1「2031年3月期（計画）」とp.10「2030年度」（期末null）が2行になったケース）。
候補は削除せず、レビュー用JSON（scripts/review_midterm_duplicate_candidates.py）で人手・Chatが判断する。

候補の条件（すべて満たす組）:
- 指標名・値（null以外）・単位・segment・consolidation_label・revision_role・target_scope・bound・value_upperが同じ
- 両方のページが分かっていて、別のページにある
- target_period_labelかtarget_fiscal_endが違う
- 期末・期間ラベルから読める決算年（「2030年度」は2030年か2031年の期末）に重なりがあるか、どちらかが読めない

検査の条件を変えたら DETECTOR_VERSION を上げること（レビュー用JSONに記録する）。
"""

import hashlib
import json
import re
import unicodedata

DETECTOR_VERSION = "midterm_duplicate_detector:1"
CANDIDATE_KIND = "possible_duplicate_target"

GROUP_FIELDS = (
    "name", "value", "unit", "segment", "consolidation_label", "revision_role",
    "target_scope", "bound", "value_upper",
)
IDENTITY_FIELDS = GROUP_FIELDS + ("target_period_label", "target_fiscal_end", "page")

_FISCAL_END = re.compile(r"^(\d{4})/(\d{2})$")
_MONTH_PERIOD = re.compile(r"(\d{4})年(\d{1,2})月期?")
_FISCAL_YEAR = re.compile(r"(\d{4})年度|FY(\d{4})", re.IGNORECASE)


def _fiscal_end_year(value):
    match = _FISCAL_END.match(value) if isinstance(value, str) else None
    return int(match.group(1)) if match else None


def possible_fiscal_end_years(item: dict):
    """期末とラベルから読める「期末の西暦年」の集合。読めなければNone。

    「2031年3月期」は2031年、「2030年度」「FY2030」は3月決算なら2031年・12月決算なら2030年のどちらか。
    """
    years = set()
    fiscal_end_year = _fiscal_end_year(item.get("target_fiscal_end"))
    if fiscal_end_year is not None:
        years.add(fiscal_end_year)
    label = item.get("target_period_label")
    if isinstance(label, str):
        text = re.sub(r"\s", "", unicodedata.normalize("NFKC", label))
        for match in _MONTH_PERIOD.finditer(text):
            years.add(int(match.group(1)))
        for match in _FISCAL_YEAR.finditer(text):
            year = int(match.group(1) or match.group(2))
            years.update({year, year + 1})
    return years or None


def _is_page(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _group_key(item: dict):
    return tuple(json.dumps(item.get(field), ensure_ascii=False) if field != "value" else item.get(field)
                 for field in GROUP_FIELDS)


def _reasons(a: dict, b: dict) -> list[str]:
    end_a, end_b = a.get("target_fiscal_end"), b.get("target_fiscal_end")
    if end_a is None and end_b is None:
        reasons = ["fiscal_end_missing_both"]
    elif end_a is None or end_b is None:
        reasons = ["fiscal_end_missing_one_side"]
    elif end_a != end_b:
        reasons = ["fiscal_end_differs"]
    else:
        reasons = ["same_fiscal_end_not_merged"]
    if a.get("target_period_label") != b.get("target_period_label"):
        reasons.append("period_label_differs")
    return reasons


def _is_candidate(a: dict, b: dict) -> bool:
    if not (_is_page(a.get("page")) and _is_page(b.get("page"))) or a["page"] == b["page"]:
        return False
    if (a.get("target_period_label") == b.get("target_period_label")
            and a.get("target_fiscal_end") == b.get("target_fiscal_end")):
        return False
    years_a, years_b = possible_fiscal_end_years(a), possible_fiscal_end_years(b)
    return years_a is None or years_b is None or bool(years_a & years_b)


def _describe(item: dict) -> str:
    return f"p.{item.get('page')}「{item.get('target_period_label')}」(期末={item.get('target_fiscal_end')})"


def candidate_id(a: dict, b: dict) -> str:
    """候補の組の識別子。行の順序・metrics内の位置・value_textに依らない。"""
    rows = sorted(json.dumps({f: row.get(f) for f in IDENTITY_FIELDS}, ensure_ascii=False, sort_keys=True)
                  for row in (a, b))
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()[:16]


def find_possible_duplicate_targets(metrics) -> list[dict]:
    """metricsから重複候補の組を返す。metricsは変更しない。"""
    if not isinstance(metrics, list):
        return []
    groups: dict = {}
    for index, item in enumerate(metrics):
        if isinstance(item, dict) and item.get("value") is not None:
            groups.setdefault(_group_key(item), []).append(index)

    candidates = []
    for indexes in groups.values():
        for pos, i in enumerate(indexes):
            for j in indexes[pos + 1:]:
                a, b = metrics[i], metrics[j]
                if not _is_candidate(a, b):
                    continue
                candidates.append({
                    "kind": CANDIDATE_KIND,
                    "candidate_id": candidate_id(a, b),
                    "metric_indexes": [i, j],
                    "pages": [a["page"], b["page"]],
                    "reasons": _reasons(a, b),
                    "detail": (f"{a.get('name')} {a.get('value')}{a.get('unit') or ''}: "
                               f"{_describe(a)} と {_describe(b)} は同じ期の同じ目標の可能性"),
                    "rows": [dict(a), dict(b)],
                    "resolution": None,
                })
    return sorted(candidates, key=lambda c: c["metric_indexes"])
