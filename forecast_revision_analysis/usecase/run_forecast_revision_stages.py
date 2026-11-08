"""会社予想修正のタイトル判定（withdrawn）とStage1/Stage2の実行・run記録。"""

from forecast_revision_analysis.usecase import extract_forecast_revision_stage1 as stage1_text_module
from forecast_revision_analysis.usecase import extract_forecast_revision_stage1_native as stage1_native_module
from forecast_revision_analysis.usecase import infer_forecast_revision_stage2 as stage2_module
from forecast_revision_analysis.usecase.build_stage2_context import build_stage2_context
from forecast_revision_analysis.usecase.extract_forecast_revision_stage1 import extract_forecast_revision_stage1
from forecast_revision_analysis.usecase.extract_forecast_revision_stage1_native import extract_forecast_revision_stage1_native
from forecast_revision_analysis.usecase.infer_forecast_revision_stage2 import infer_forecast_revision_stage2
from forecast_revision_analysis.usecase.merge_stage_results import merge_stage_results
from tdnet_provenance.usecase.prepare_pdf_input import PdfInput
from tdnet_provenance.usecase.provenance_recorder import (
    ProvenanceRecorder,
    module_llm_settings,
    run_llm_stage,
    text_hash,
)

WITHDRAWN_KEYWORDS = [
    "予想の取り下げ", "予想を取り下げ",
    "予想の廃止", "予想を廃止",
    "予想の撤回", "予想を撤回",
]


def find_withdrawn_keyword(title: str) -> str | None:
    return next((kw for kw in WITHDRAWN_KEYWORDS if kw in title), None)


def record_withdrawn_route(recorder: ProvenanceRecorder | None, *, url: str, title: str) -> bool:
    """タイトルが業績予想の取り下げならTrue。recorderがあれば判断runだけを残す（PDF取得前なのでsource_hashはNULL）。"""
    keyword = find_withdrawn_keyword(title)
    if keyword is None:
        return False
    if recorder is not None:
        recorder.record_decision(
            url=url, stage="eligibility", outcome="withdrawn",
            outcome_reason=f"title_keyword:{keyword}",
            input_payload={"title": title, "rule": "forecast_withdrawn_title", "keywords": WITHDRAWN_KEYWORDS},
        )
    return True


def run_stage1_and_stage2(recorder: ProvenanceRecorder | None, pdf_input: PdfInput, *, title, code, name) -> dict | None:
    """Stage1（抽出）を実行し、成功すればStage2（推論）を実行してマージした結果を返す。

    Stage1が失敗した場合はNoneを返す。Stage2が失敗した場合でもStage1のデータは失わない
    （direct_factors等はNoneのまま保存する。詳細はdocs/forecast_revision_llm_pipeline_redesign.md §5）。
    recorderがあればStage1/Stage2を別々のrunとして記録する。
    """
    stage1_input = {"title": title, "code": code, "name": name}
    if pdf_input.pdf_path is not None:
        stage1_obj = run_llm_stage(
            recorder, pdf_input.source, stage="stage1", prompt_name=stage1_native_module.PROMPT_FILENAME,
            input_payload=stage1_input, **module_llm_settings(stage1_native_module),
            call=lambda: extract_forecast_revision_stage1_native(
                title=title, pdf_path=pdf_input.pdf_path, code=code, name=name,
            ),
        )
    else:
        stage1_obj = run_llm_stage(
            recorder, pdf_input.source, stage="stage1", prompt_name=stage1_text_module.PROMPT_FILENAME,
            input_payload={**stage1_input, "text_sha256": text_hash(pdf_input.content)},
            **module_llm_settings(stage1_text_module),
            call=lambda: extract_forecast_revision_stage1(
                title=title, content=pdf_input.content, code=code, name=name,
            ),
        )

    if stage1_obj is None:
        return None

    stage2_context = build_stage2_context(stage1_obj, title=title, code=code, name=name)
    stage2_obj = run_llm_stage(
        recorder, pdf_input.source, stage="stage2", prompt_name=stage2_module.PROMPT_FILENAME,
        input_payload={"context_sha256": text_hash(stage2_context)}, **module_llm_settings(stage2_module),
        call=lambda: infer_forecast_revision_stage2(stage2_context),
    )
    return merge_stage_results(stage1_obj, stage2_obj)
