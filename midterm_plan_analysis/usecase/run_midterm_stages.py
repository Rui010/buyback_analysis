"""中計のLLM stage（metrics・keywords・classification）の実行とrun記録。

native/textはPdfInputのどちらの値があるかで決まる。recorderがNoneならrunを記録しない。
"""

from buyback_analysis.usecase import classify_midterm_by_llm as classify_module
from buyback_analysis.usecase.classify_midterm_by_llm import classify_midterm_by_llm
from buyback_analysis.usecase.parse_pdf_by_llm import parse_pdf_by_llm
from buyback_analysis.usecase.parse_text_by_llm import parse_text_by_llm
from midterm_plan_analysis.usecase import extract_midterm_keywords as keywords_text
from midterm_plan_analysis.usecase import extract_midterm_keywords_native as keywords_native
from midterm_plan_analysis.usecase.extract_midterm_keywords import extract_midterm_keywords
from midterm_plan_analysis.usecase.extract_midterm_keywords_native import extract_midterm_keywords_native
from tdnet_provenance.usecase.prepare_pdf_input import PdfInput
from tdnet_provenance.usecase.provenance_recorder import ProvenanceRecorder, run_llm_stage, text_hash

METRICS_PROMPT_NATIVE = "midterm_plan_native.md"
METRICS_PROMPT_TEXT = "midterm_plan.md"


def _llm_input(pdf_input: PdfInput, title, code, name) -> dict:
    payload = {"title": title, "code": code, "name": name}
    if pdf_input.content is not None:
        payload["text_sha256"] = text_hash(pdf_input.content)
    return payload


def run_midterm_metrics(recorder: ProvenanceRecorder | None, pdf_input: PdfInput, *, title, code, name):
    if pdf_input.pdf_path is not None:
        prompt, call = METRICS_PROMPT_NATIVE, lambda: parse_pdf_by_llm(
            title=title, pdf_path=pdf_input.pdf_path, code=code, name=name, prompt_filename=METRICS_PROMPT_NATIVE,
        )
    else:
        prompt, call = METRICS_PROMPT_TEXT, lambda: parse_text_by_llm(
            title=title, content=pdf_input.content, code=code, name=name, prompt_filename=METRICS_PROMPT_TEXT,
        )
    return run_llm_stage(
        recorder, pdf_input.source, stage="metrics", prompt_name=prompt,
        input_payload=_llm_input(pdf_input, title, code, name), call=call,
    )


def run_midterm_keywords(recorder: ProvenanceRecorder | None, pdf_input: PdfInput, *, title, code, name):
    if pdf_input.pdf_path is not None:
        prompt, call = keywords_native.PROMPT_FILENAME, lambda: extract_midterm_keywords_native(
            title=title, pdf_path=pdf_input.pdf_path, code=code, name=name,
        )
    else:
        prompt, call = keywords_text.PROMPT_FILENAME, lambda: extract_midterm_keywords(
            title=title, content=pdf_input.content, code=code, name=name,
        )
    return run_llm_stage(
        recorder, pdf_input.source, stage="keywords", prompt_name=prompt,
        input_payload=_llm_input(pdf_input, title, code, name), call=call,
    )


def run_midterm_classification(recorder: ProvenanceRecorder | None, pdf_input: PdfInput, *, title, code, name) -> str:
    """metricsが空だった文書を分類する。native方式では従来どおり空文字を渡す。"""
    content = pdf_input.content or ""
    return run_llm_stage(
        recorder, pdf_input.source, stage="classification", prompt_name=classify_module.PROMPT_FILENAME,
        input_payload={"title": title, "code": code, "name": name, "text_sha256": text_hash(content)},
        call=lambda: classify_midterm_by_llm(title=title, content=content, code=code, name=name),
        is_success=lambda status: status != "failed",
    )
