from types import SimpleNamespace

from buyback_analysis.interface.llm_usage import capture_llm_usage, report_llm_response


def _response(prompt, candidates, thoughts=None, response_id="req-1"):
    return SimpleNamespace(
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt, candidates_token_count=candidates, thoughts_token_count=thoughts,
        ),
        response_id=response_id,
    )


def test_collects_tokens_and_request_ids():
    with capture_llm_usage() as usage:
        report_llm_response(_response(100, 20, thoughts=5, response_id="a"))
        report_llm_response(_response(10, 2, response_id="b"))
    assert usage.input_tokens == 110
    assert usage.output_tokens == 27
    assert usage.request_ids == ["a", "b"]
    assert usage.last_request_id == "b"


def test_outside_capture_is_noop():
    report_llm_response(_response(100, 20))  # 例外にならない


def test_missing_metadata_is_tolerated():
    with capture_llm_usage() as usage:
        report_llm_response(SimpleNamespace())
    assert (usage.input_tokens, usage.output_tokens, usage.last_request_id) == (0, 0, None)


def test_nested_capture_is_isolated():
    with capture_llm_usage() as outer:
        with capture_llm_usage() as inner:
            report_llm_response(_response(1, 1))
        report_llm_response(_response(2, 2))
    assert inner.input_tokens == 1
    assert outer.input_tokens == 2
