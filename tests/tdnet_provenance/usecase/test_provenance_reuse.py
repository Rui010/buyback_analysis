"""Step 3: 成功runの再利用・token/費用の記録・generation_configの記録。"""

import datetime
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from buyback_analysis.interface.llm_usage import report_llm_response
from tdnet_provenance.models.base import ProvenanceBase
from tdnet_provenance.models.processing_run import ProcessingRun
from tdnet_provenance.models.run_output import RunOutput
from tdnet_provenance.usecase.provenance_recorder import (
    LlmPricing,
    ProvenanceRecorder,
    describe_generation_config,
)
from tdnet_provenance.usecase.resolve_verified_source import VerifiedSource

COMMIT = "0123456789abcdef0123456789abcdef01234567"
URL = "https://www.release.tdnet.info/inbs/140120260218512345.pdf"
SOURCE = VerifiedSource(
    url=URL, source_document_id="doc", external_document_id="140120260218512345",
    storage_uri="tdnet-pdf://20260219/140120260218512345.pdf", source_hash="a" * 64, path=Path("/x.pdf"),
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    ProvenanceBase.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True)() as s:
        yield s


def _recorder(session, **kwargs):
    times = iter(datetime.datetime(2026, 2, 19, tzinfo=datetime.timezone.utc) + datetime.timedelta(seconds=i)
                 for i in range(1000))
    return ProvenanceRecorder(session, code_commit=COMMIT, clock=lambda: next(times), **kwargs)


class Counter:
    """LLM関数の代役。呼ばれた回数を数え、使用量を報告する。"""

    def __init__(self, result=None, prompt_tokens=1000, output_tokens=200):
        self.result = {"data": {"metrics": [1]}} if result is None else result
        self.calls = 0
        self.prompt_tokens = prompt_tokens
        self.output_tokens = output_tokens

    def __call__(self):
        self.calls += 1
        report_llm_response(SimpleNamespace(
            usage_metadata=SimpleNamespace(prompt_token_count=self.prompt_tokens,
                                           candidates_token_count=self.output_tokens, thoughts_token_count=0),
            response_id=f"req-{self.calls}",
        ))
        return self.result


def _run(recorder, call, **overrides):
    kwargs = dict(source=SOURCE, stage="metrics", prompt_name="midterm_plan.md",
                  input_payload={"title": "t"}, call=call, extractor_version="parse_text_by_llm:1")
    kwargs.update(overrides)
    return recorder.run_llm(**kwargs)


def _runs(session):
    return session.query(ProcessingRun).order_by(ProcessingRun.started_at).all()


def test_tokens_and_request_id_are_recorded(session):
    _run(_recorder(session), Counter(prompt_tokens=1000, output_tokens=200))
    [run] = _runs(session)
    assert (run.input_tokens, run.output_tokens, run.provider_request_id) == (1000, 200, "req-1")
    assert run.estimated_cost is None and run.estimated_cost_currency is None  # 単価未指定
    assert run.extractor_version == "parse_text_by_llm:1"


def test_cost_is_calculated_from_pricing(session):
    pricing = LlmPricing(input_per_million=10.0, output_per_million=40.0, currency="JPY")
    _run(_recorder(session, pricing=pricing), Counter(prompt_tokens=1_000_000, output_tokens=500_000))
    [run] = _runs(session)
    assert run.estimated_cost == 30.0
    assert run.estimated_cost_currency == "JPY"


def test_same_conditions_reuse_without_calling_llm(session):
    pricing = LlmPricing(1.0, 1.0, "JPY")
    recorder = _recorder(session, pricing=pricing)
    first = Counter(result={"data": {"metrics": ["初回"]}})
    _run(recorder, first)
    second = Counter()

    result = _run(recorder, second)

    assert second.calls == 0
    assert result == {"data": {"metrics": ["初回"]}}
    original, reused = _runs(session)
    assert reused.status == "reused"
    assert reused.reused_run_id == original.run_id
    assert (reused.input_tokens, reused.output_tokens, reused.estimated_cost) == (0, 0, 0.0)
    assert reused.estimated_cost_currency == "JPY"
    assert reused.reuse_key == original.reuse_key
    assert session.get(RunOutput, reused.run_id) is None  # 再利用runは出力を重複保存しない


@pytest.mark.parametrize(
    "override",
    [
        {"extractor_version": "parse_text_by_llm:2"},
        {"prompt_name": "midterm_plan_native.md"},
        {"input_payload": {"title": "別タイトル"}},
        {"generation_config": {"temperature": 0.5}},
        {"source": VerifiedSource(**{**SOURCE.__dict__, "source_hash": "b" * 64})},
    ],
)
def test_changed_conditions_call_llm_again(session, override):
    recorder = _recorder(session)
    _run(recorder, Counter())
    second = Counter()
    _run(recorder, second, **override)
    assert second.calls == 1
    assert [r.status for r in _runs(session)] == ["succeeded", "succeeded"]


def test_force_does_not_reuse(session):
    _run(_recorder(session), Counter())
    second = Counter()
    _run(_recorder(session, force=True), second)
    assert second.calls == 1


def test_first_run_of_retry_does_not_reuse(session):
    recorder = _recorder(session)
    _run(recorder, Counter())  # 成功run（再利用の候補）
    failing = Counter()
    failing.result = None
    _run(recorder, failing, input_payload={"title": "失敗"})  # 同じURLの失敗run
    recorder.start_document(URL, retry=True)
    assert recorder._pending_retry_of is not None
    second = Counter()
    _run(recorder, second)
    assert second.calls == 1


@pytest.mark.parametrize("result,is_success", [(None, None), ("failed", lambda r: r != "failed")])
def test_failed_runs_are_not_reused(session, result, is_success):
    recorder = _recorder(session)
    kwargs = {"is_success": is_success} if is_success else {}
    first = Counter(result=result)
    first.result = result
    _run(recorder, first, **kwargs)
    second = Counter(result={"data": {}})
    _run(recorder, second, **kwargs)
    assert second.calls == 1
    assert session.query(RunOutput).count() == 1  # 成功した2回目の出力だけ


def test_failed_run_records_tokens_spent(session):
    def broken():
        report_llm_response(SimpleNamespace(
            usage_metadata=SimpleNamespace(prompt_token_count=50, candidates_token_count=5, thoughts_token_count=None),
            response_id="req-x",
        ))
        raise SystemExit("API制限")

    with pytest.raises(SystemExit):
        _run(_recorder(session), broken)
    [run] = _runs(session)
    assert (run.status, run.input_tokens, run.output_tokens) == ("failed", 50, 5)


def test_non_json_output_is_not_stored(session):
    _run(_recorder(session), lambda: {"value": object()})
    [run] = _runs(session)
    assert run.status == "succeeded"
    assert session.get(RunOutput, run.run_id) is None


def test_output_is_stored_as_json(session):
    _run(_recorder(session), Counter(result={"data": {"plan_name": "計画"}}))
    [output] = session.query(RunOutput).all()
    assert json.loads(output.output) == {"data": {"plan_name": "計画"}}


class _Schema(BaseModel):
    keyword: str


def test_generation_config_describes_pydantic_schema(session):
    described = describe_generation_config({"response_schema": _Schema, "temperature": 0.0})
    assert described["temperature"] == 0.0
    assert described["response_schema"]["pydantic_model"].endswith("._Schema")
    assert len(described["response_schema"]["schema_sha256"]) == 64

    _run(_recorder(session), Counter(), generation_config={"response_schema": _Schema})
    assert json.loads(_runs(session)[0].generation_config)["response_schema"] == described["response_schema"]


def test_pricing_from_env():
    assert LlmPricing.from_env({}) is None
    pricing = LlmPricing.from_env({
        "LLM_PRICE_INPUT_PER_1M_TOKENS": "15", "LLM_PRICE_OUTPUT_PER_1M_TOKENS": "60", "LLM_PRICE_CURRENCY": "JPY",
    })
    assert pricing == LlmPricing(15.0, 60.0, "JPY")


@pytest.mark.parametrize(
    "env",
    [
        {"LLM_PRICE_INPUT_PER_1M_TOKENS": "15"},
        {"LLM_PRICE_INPUT_PER_1M_TOKENS": "x", "LLM_PRICE_OUTPUT_PER_1M_TOKENS": "1", "LLM_PRICE_CURRENCY": "JPY"},
    ],
)
def test_pricing_from_env_rejects_partial_or_invalid(env):
    with pytest.raises(ValueError):
        LlmPricing.from_env(env)


@pytest.mark.parametrize(
    "env,expected_force",
    [
        ({}, False),  # 通常処理は再利用する
        ({"RERUN_URLS": "https://x/a.pdf"}, True),  # RERUNは既定でLLMを呼び直す
        ({"RERUN_URLS": "https://x/a.pdf", "RERUN_ALLOW_REUSE": "true"}, False),
        ({"RERUN_URLS": " , "}, False),
        ({"RERUN_ALLOW_REUSE": "true"}, False),
    ],
)
def test_from_env_force_follows_rerun(session, env, expected_force):
    recorder = ProvenanceRecorder.from_env(session, env={
        "TDNET_PROVENANCE_ENABLED": "true", "CODE_COMMIT": COMMIT,
        "LLM_PRICE_INPUT_PER_1M_TOKENS": "1", "LLM_PRICE_OUTPUT_PER_1M_TOKENS": "2", "LLM_PRICE_CURRENCY": "USD",
        **env,
    })
    assert recorder.force is expected_force
    assert recorder.pricing == LlmPricing(1.0, 2.0, "USD")


def test_rerun_with_same_conditions_calls_llm_again(session):
    # 誤抽出の修正でRERUNしたとき、同じ誤った出力を再利用しない
    _run(_recorder(session), Counter(result={"data": {"metrics": ["誤り"]}}))
    rerun = ProvenanceRecorder.from_env(session, env={
        "TDNET_PROVENANCE_ENABLED": "true", "CODE_COMMIT": COMMIT, "RERUN_URLS": URL,
    })
    second = Counter(result={"data": {"metrics": ["修正後"]}})
    assert _run(rerun, second) == {"data": {"metrics": ["修正後"]}}
    assert second.calls == 1
