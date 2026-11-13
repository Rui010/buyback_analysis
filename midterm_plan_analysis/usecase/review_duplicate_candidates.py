"""中計の採用版（midterm_plans）から重複候補を探し、レビュー用JSONの中身を作る。読み取りだけで、何も書かない。

レビュー用JSONの各entryは、修正の前提（採用version ID・source hash）と修正対象のresult
（post_midterm_planに渡す形 {"type", "data"}）を持つ。人手・Chatはresultのmetricsを直し、各候補の
resolutionに "merged"（1行にまとめた）か "distinct"（別の目標なので両方残す）を書く。
直したJSONは scripts/import_midterm_verified_results.py で取り込む（import_reviewed_result.pyが検証する）。
"""

import json

from midterm_plan_analysis.models.midterm_plan import MidtermPlan
from midterm_plan_analysis.usecase.detect_duplicate_candidates import (
    DETECTOR_VERSION,
    find_possible_duplicate_targets,
)
from midterm_plan_analysis.usecase.save_midterm_result import MIDTERM_RESULT_TYPE
from tdnet_provenance.models.processing_run import ProcessingRun
from tdnet_provenance.models.result_adoption import ResultAdoption
from tdnet_provenance.models.result_version import ResultVersion
from tdnet_provenance.models.tdnet_source_document import TdnetSourceDocument

REVIEW_KIND = "midterm_duplicate_review"
REVIEW_FORMAT_VERSION = 1
RESULT_TYPE_LABEL = "MIDTERM_PLAN"
PLAN_FIELDS = (
    "plan_name", "plan_start_year", "plan_end_year", "plan_start_period_label", "plan_end_period_label",
    "plan_start_fiscal_end", "plan_end_fiscal_end",
)
INSTRUCTIONS = (
    "各entryのresult.data.metricsを直し、candidatesの各resolutionに merged（1行にまとめた）か "
    "distinct（別の目標なので両方残す）を書く。adopted_version_id・source_hash・candidatesのcandidate_idは変えない。"
    "取込み時にschema・値・期末・重複を再検査し、再検出された候補がdistinctでなければそのURLは採用しない。"
)


def _metrics_run(session, run_ids: list[str]):
    if not run_ids:
        return None
    runs = (session.query(ProcessingRun)
            .filter(ProcessingRun.run_id.in_(run_ids), ProcessingRun.stage == "metrics").all())
    preferred = [r for r in runs if r.status in ("succeeded", "reused")]
    return (preferred or runs or [None])[0]


def current_review_state(session, url: str) -> dict:
    """そのURLの現在の採用version ID・source hash・metrics stageのprompt hash。"""
    adoption = (session.query(ResultAdoption)
                .filter(ResultAdoption.url == url, ResultAdoption.result_type == MIDTERM_RESULT_TYPE)
                .order_by(ResultAdoption.adopted_at.desc()).first())
    version = session.get(ResultVersion, adoption.version_id) if adoption is not None else None
    source = session.get(TdnetSourceDocument, url)
    run_ids = json.loads(version.run_ids) if version is not None else []
    run = _metrics_run(session, run_ids)
    return {
        "adopted_version_id": adoption.version_id if adoption is not None else None,
        "version_origin": version.origin if version is not None else None,
        "source_hash": source.source_hash if source is not None else None,
        "run_ids": run_ids,
        "prompt_name": run.prompt_name if run is not None else None,
        "prompt_hash": run.prompt_hash if run is not None else None,
    }


def _load_list(text):
    try:
        value = json.loads(text) if text is not None else None
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, list) else None


def plan_result(plan: MidtermPlan) -> dict | None:
    """midterm_plansの行をpost_midterm_planに渡す形にする。metricsが読めなければNone。"""
    metrics = _load_list(plan.metrics)
    if metrics is None:
        return None
    data = {field: getattr(plan, field) for field in PLAN_FIELDS}
    data["metrics"] = metrics
    data["reference_values"] = _load_list(plan.reference_values)
    return {"type": RESULT_TYPE_LABEL, "data": data}


def build_review_entries(session, urls=None) -> list[dict]:
    """extraction_status=okの採用行のうち、重複候補がある文書のentryを返す（開示日・URL順）。"""
    query = session.query(MidtermPlan).filter(MidtermPlan.extraction_status == "ok")
    if urls:
        query = query.filter(MidtermPlan.url.in_(list(urls)))
    entries = []
    for plan in query.order_by(MidtermPlan.disclosure_date, MidtermPlan.url).all():
        result = plan_result(plan)
        if result is None:
            continue
        candidates = find_possible_duplicate_targets(result["data"]["metrics"])
        if not candidates:
            continue
        entries.append({
            "url": plan.url,
            "code": plan.code,
            "disclosure_date": plan.disclosure_date,
            "extraction_status": plan.extraction_status,
            **current_review_state(session, plan.url),
            "result": result,
            "candidates": candidates,
        })
    return entries


def build_review_document(entries: list[dict], *, generated_at: str) -> dict:
    return {
        "kind": REVIEW_KIND,
        "format_version": REVIEW_FORMAT_VERSION,
        "detector_version": DETECTOR_VERSION,
        "generated_at": generated_at,
        "instructions": INSTRUCTIONS,
        "entries": entries,
    }
