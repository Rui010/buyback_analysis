"""中計のLLM stage（metrics・keywords・classification）の実行とrun記録。

native/textはPdfInputのどちらの値があるかで決まる。recorderがNoneならrunを記録しない。
"""

from buyback_analysis.usecase import classify_midterm_by_llm as classify_module
from buyback_analysis.usecase.classify_midterm_by_llm import classify_midterm_by_llm
from buyback_analysis.usecase import parse_pdf_by_llm as parse_pdf_module
from buyback_analysis.usecase import parse_text_by_llm as parse_text_module
from buyback_analysis.usecase.parse_pdf_by_llm import parse_pdf_by_llm
from buyback_analysis.usecase.parse_text_by_llm import parse_text_by_llm
from midterm_plan_analysis.usecase import extract_midterm_keywords as keywords_text
from midterm_plan_analysis.usecase import extract_midterm_keywords_native as keywords_native
from midterm_plan_analysis.usecase.extract_midterm_keywords import extract_midterm_keywords
from midterm_plan_analysis.usecase.extract_midterm_keywords_native import extract_midterm_keywords_native
from midterm_plan_analysis.usecase.normalize_midterm_metrics import NORMALIZER_VERSION, normalize_midterm_result
from tdnet_provenance.usecase.prepare_pdf_input import PdfInput
from tdnet_provenance.usecase.provenance_recorder import (
    ProvenanceRecorder,
    module_llm_settings,
    run_llm_stage,
    text_hash,
)

METRICS_PROMPT_NATIVE = "midterm_plan_native.md"
METRICS_PROMPT_TEXT = "midterm_plan.md"


def _llm_input(pdf_input: PdfInput, title, code, name, content: str | None = None) -> dict:
    payload = {"title": title, "code": code, "name": name}
    content = pdf_input.content if content is None else content
    if content is not None:
        payload["text_sha256"] = text_hash(content)
    return payload


def run_midterm_metrics(recorder: ProvenanceRecorder | None, pdf_input: PdfInput, *, title, code, name):
    """metricsを抽出し、正規化（normalize_midterm_result）した結果を返す。失敗時はNone。

    text方式でpaged_content（ページの目印入り）があればそれを送る。目印のない入力ではpageをnullにする。
    正規化後の結果をrunの出力として記録するため、extractor_versionに正規化の版を含める。
    """
    if pdf_input.pdf_path is not None:
        module, prompt, content, page_available = parse_pdf_module, METRICS_PROMPT_NATIVE, None, True
        extract = lambda: parse_pdf_by_llm(  # noqa: E731
            title=title, pdf_path=pdf_input.pdf_path, code=code, name=name, prompt_filename=METRICS_PROMPT_NATIVE,
        )
    else:
        page_available = pdf_input.paged_content is not None
        content = pdf_input.paged_content if page_available else pdf_input.content
        module, prompt = parse_text_module, METRICS_PROMPT_TEXT
        extract = lambda: parse_text_by_llm(  # noqa: E731
            title=title, content=content, code=code, name=name, prompt_filename=METRICS_PROMPT_TEXT,
        )

    def call():
        return normalize_midterm_result(extract(), page_available=page_available, log_context=f"{code} - {title}")

    settings = module_llm_settings(module)
    settings["extractor_version"] = f"{settings['extractor_version']}+{NORMALIZER_VERSION}"
    return run_llm_stage(
        recorder, pdf_input.source, stage="metrics", prompt_name=prompt,
        input_payload=_llm_input(pdf_input, title, code, name, content), call=call, **settings,
    )


def run_midterm_keywords(recorder: ProvenanceRecorder | None, pdf_input: PdfInput, *, title, code, name):
    module = keywords_native if pdf_input.pdf_path is not None else keywords_text
    if pdf_input.pdf_path is not None:
        call = lambda: extract_midterm_keywords_native(  # noqa: E731
            title=title, pdf_path=pdf_input.pdf_path, code=code, name=name,
        )
    else:
        call = lambda: extract_midterm_keywords(  # noqa: E731
            title=title, content=pdf_input.content, code=code, name=name,
        )
    return run_llm_stage(
        recorder, pdf_input.source, stage="keywords", prompt_name=module.PROMPT_FILENAME,
        input_payload=_llm_input(pdf_input, title, code, name), call=call, **module_llm_settings(module),
    )


def run_midterm_classification(recorder: ProvenanceRecorder | None, pdf_input: PdfInput, *, title, code, name) -> str:
    """metricsが空だった文書を分類する。native方式では従来どおり空文字を渡す。"""
    content = pdf_input.content or ""
    return run_llm_stage(
        recorder, pdf_input.source, stage="classification", prompt_name=classify_module.PROMPT_FILENAME,
        input_payload={"title": title, "code": code, "name": name, "text_sha256": text_hash(content)},
        call=lambda: classify_midterm_by_llm(title=title, content=content, code=code, name=name),
        is_success=lambda status: status != "failed",
        **module_llm_settings(classify_module),
    )
