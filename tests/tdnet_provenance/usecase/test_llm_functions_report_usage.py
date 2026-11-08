"""8つのLLM関数が、GENERATION_CONFIGをそのままGeminiへ渡し、使用量を報告していること。

processing_runのgeneration_config・reuse keyはモジュールのGENERATION_CONFIGから作るため、
実際の呼び出しと同じ値であることをここで固定する。
"""

import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from buyback_analysis.interface.llm_usage import capture_llm_usage
from tests.forecast_revision_analysis.usecase.test_extract_forecast_revision_stage1 import VALID_JSON as STAGE1_JSON
from tests.forecast_revision_analysis.usecase.test_infer_forecast_revision_stage2 import VALID_JSON as STAGE2_JSON
from tests.midterm_plan_analysis.usecase.test_extract_midterm_keywords import VALID_JSON as KEYWORDS_JSON

DOC = dict(title="t", code="1234", name="A社")
CASES = [
    ("buyback_analysis.usecase.parse_text_by_llm", "parse_text_by_llm",
     dict(content="本文", prompt_filename="midterm_plan.md", **DOC), '{"data": {}}'),
    ("buyback_analysis.usecase.parse_pdf_by_llm", "parse_pdf_by_llm",
     dict(pdf_path="x.pdf", prompt_filename="midterm_plan_native.md", **DOC), '{"data": {}}'),
    ("buyback_analysis.usecase.classify_midterm_by_llm", "classify_midterm_by_llm",
     dict(content="本文", **DOC), '{"extraction_status": "no_targets"}'),
    ("forecast_revision_analysis.usecase.extract_forecast_revision_stage1", "extract_forecast_revision_stage1",
     dict(content="本文", **DOC), STAGE1_JSON),
    ("forecast_revision_analysis.usecase.extract_forecast_revision_stage1_native", "extract_forecast_revision_stage1_native",
     dict(pdf_path="x.pdf", **DOC), STAGE1_JSON),
    ("forecast_revision_analysis.usecase.infer_forecast_revision_stage2", "infer_forecast_revision_stage2",
     dict(context="要約"), STAGE2_JSON),
    ("midterm_plan_analysis.usecase.extract_midterm_keywords", "extract_midterm_keywords",
     dict(content="本文", **DOC), KEYWORDS_JSON),
    ("midterm_plan_analysis.usecase.extract_midterm_keywords_native", "extract_midterm_keywords_native",
     dict(pdf_path="x.pdf", **DOC), KEYWORDS_JSON),
]


@pytest.mark.parametrize("module_name,func_name,kwargs,text", CASES, ids=[c[1] for c in CASES])
def test_llm_function_uses_generation_config_and_reports_usage(monkeypatch, module_name, func_name, kwargs, text):
    module = importlib.import_module(module_name)
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(
        text=text,
        usage_metadata=SimpleNamespace(prompt_token_count=120, candidates_token_count=30, thoughts_token_count=4),
        response_id="resp-1",
    )
    patches = [
        patch.object(module, "load_dotenv", MagicMock()),
        patch.object(module.time, "sleep", MagicMock()),
        patch.object(module.genai, "Client", MagicMock(return_value=client)),
    ]
    if hasattr(module, "_extract_lead_text"):
        patches.append(patch.object(module, "_extract_lead_text", MagicMock(return_value="冒頭")))
    for p in patches:
        p.start()
    try:
        with capture_llm_usage() as usage:
            result = getattr(module, func_name)(**kwargs)
    finally:
        for p in patches:
            p.stop()

    assert result is not None
    config = client.models.generate_content.call_args.kwargs["config"]
    assert config == (module.GENERATION_CONFIG or None)
    assert (usage.input_tokens, usage.output_tokens, usage.last_request_id) == (120, 34, "resp-1")
    assert module.EXTRACTOR_VERSION.endswith(":1")
