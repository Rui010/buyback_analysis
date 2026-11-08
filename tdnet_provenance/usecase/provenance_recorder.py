"""processing runの追記記録（tdnet-provenance-v1 §4.4・§4.5）。

`TDNET_PROVENANCE_ENABLED=true`のときだけ各パイプラインが`ProvenanceRecorder`を使う。
falseのときは`run_llm_stage(None, ...)`がLLM関数をそのまま呼ぶだけで、DBにも触れない。
"""

import datetime
import hashlib
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from buyback_analysis.consts.llm_model import LlmModel
from buyback_analysis.interface.logger import Logger
from tdnet_provenance.models.base import ProvenanceBase
from tdnet_provenance.models.processing_run import ProcessingRun
from tdnet_provenance.usecase.code_version import resolve_code_commit
from tdnet_provenance.usecase.resolve_verified_source import (
    SourceVerificationError,
    VerifiedSource,
    resolve_verified_source,
)

logger = Logger()

MODEL_PROVIDER = "google"
PROMPTS_DIR = Path(__file__).resolve().parents[2] / "buyback_analysis" / "prompts"


def canonical_hash(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prompt_file_hash(prompt_name: str) -> str:
    return hashlib.sha256((PROMPTS_DIR / prompt_name).read_bytes()).hexdigest()


@dataclass(frozen=True)
class RunSpec:
    url: str | None
    source_document_id: str | None
    input_locator: str
    source_hash: str | None
    input_hash: str
    run_kind: str
    stage: str
    code_commit: str
    extractor_version: str | None = None
    prompt_name: str | None = None
    prompt_hash: str | None = None
    model_provider: str | None = None
    model_name: str | None = None
    generation_config: Mapping[str, Any] = field(default_factory=dict)

    def reuse_key(self) -> str:
        """ir_analytics_contract.processing.RunSpec.reuse_key() と同じ正規化。"""
        return canonical_hash({
            "source_hash": self.source_hash,
            "input_hash": self.input_hash,
            "run_kind": self.run_kind,
            "stage": self.stage,
            "extractor_version": self.extractor_version or self.code_commit,
            "prompt_hash": self.prompt_hash,
            "model_provider": self.model_provider,
            "model_name": self.model_name,
            "generation_config": dict(self.generation_config),
        })


class RunPersistError(RuntimeError):
    """runを保存できない。抽出結果だけを孤立保存しないよう、呼び出し側は処理を止める。"""


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class ProvenanceRecorder:
    def __init__(self, session, code_commit: str, clock=_utc_now, resolver=None):
        self.session = session
        self.code_commit = code_commit
        self.clock = clock
        self.resolver = resolver or resolve_verified_source
        self._document_run_ids: list[str] = []
        self._pending_retry_of: str | None = None

    def start_document(self, url: str, *, retry: bool = False) -> None:
        """1文書の処理開始時に呼ぶ。retry=True（現行結果がfailed）なら、このURLの直近の
        failed runを今回最初に記録するrunのretry_of_run_idにする（failed runは削除しない）。"""
        self._document_run_ids = []
        self._pending_retry_of = None
        if retry:
            latest_failed = (
                self.session.query(ProcessingRun.run_id)
                .filter(ProcessingRun.url == url, ProcessingRun.status == "failed")
                .order_by(ProcessingRun.completed_at.desc())
                .first()
            )
            self._pending_retry_of = latest_failed[0] if latest_failed else None

    @property
    def document_run_ids(self) -> list[str]:
        """start_document()以降に記録したrun（結果versionのrun_idsになる）。"""
        return list(self._document_run_ids)

    @classmethod
    def from_env(cls, session, env=None) -> "ProvenanceRecorder | None":
        env = os.environ if env is None else env
        if (env.get("TDNET_PROVENANCE_ENABLED") or "false").lower() != "true":
            return None
        from tdnet_provenance.usecase.adopt_result import ensure_provenance_tables

        ensure_provenance_tables(session)
        return cls(session, code_commit=resolve_code_commit(env=env))

    def _now(self) -> str:
        return self.clock().isoformat()

    def _append(self, spec: RunSpec, *, status, started_at, error_code=None, outcome=None, outcome_reason=None):
        run_id = str(uuid4())
        row = ProcessingRun(
            run_id=run_id,
            url=spec.url,
            source_document_id=spec.source_document_id,
            input_locator=spec.input_locator,
            source_hash=spec.source_hash,
            input_hash=spec.input_hash,
            run_kind=spec.run_kind,
            stage=spec.stage,
            code_commit=spec.code_commit,
            extractor_version=spec.extractor_version,
            prompt_name=spec.prompt_name,
            prompt_hash=spec.prompt_hash,
            model_provider=spec.model_provider,
            model_name=spec.model_name,
            generation_config=json.dumps(dict(spec.generation_config), ensure_ascii=False, sort_keys=True),
            reuse_key=spec.reuse_key(),
            status=status,
            outcome=outcome,
            outcome_reason=outcome_reason,
            started_at=started_at,
            completed_at=self._now(),
            retry_of_run_id=self._pending_retry_of,
            error_code=error_code,
        )
        self.session.add(row)
        try:
            self.session.commit()
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise RunPersistError(f"processing_runの保存に失敗しました: {exc}") from exc
        self._pending_retry_of = None
        self._document_run_ids.append(run_id)
        return row

    def _failure_spec(self, *, url, stage, source: VerifiedSource | None) -> RunSpec:
        return RunSpec(
            url=url,
            source_document_id=source.source_document_id if source else None,
            input_locator=source.storage_uri if source else url,
            source_hash=source.source_hash if source else None,
            input_hash=canonical_hash({"url": url}),
            run_kind="extract",
            stage=stage,
            code_commit=self.code_commit,
            extractor_version=self.code_commit,  # 抽出器の論理版は未管理のため、コード版をそのまま版とする
        )

    def record_source_failure(self, *, url, stage, error_code, source: VerifiedSource | None = None):
        """PDF取得・読取・hash照合の失敗を、開始したstageのfailed runとして残す。LLMは呼ばない。"""
        started_at = self._now()
        return self._append(self._failure_spec(url=url, stage=stage, source=source),
                            status="failed", started_at=started_at, error_code=error_code)

    def resolve_source(self, *, url, disclosure_date, time, pdf_root, stage) -> VerifiedSource | None:
        started_at = self._now()
        try:
            return self.resolver(
                self.session, url=url, disclosure_date=disclosure_date, time=time, pdf_root=pdf_root
            )
        except SourceVerificationError as exc:
            logger.error(f"[Provenance] 原典を確定できません [{exc.error_code}]: {url} {exc}")
            self._append(self._failure_spec(url=url, stage=stage, source=None),
                         status="failed", started_at=started_at, error_code=exc.error_code)
            return None

    def run_llm(
        self,
        *,
        source: VerifiedSource,
        stage: str,
        prompt_name: str,
        input_payload: Mapping[str, Any],
        call: Callable[[], Any],
        generation_config: Mapping[str, Any] | None = None,
        is_success: Callable[[Any], bool] = lambda result: result is not None,
    ):
        """LLM stageを実行し、終了状態のrunを1行追記して結果を返す。

        generation_configはStep 1では記録しない（{}）。LLM関数内の設定にはresponse_schema等の
        JSON化できない値が含まれ、呼び出し側へ写すとずれるため、Step 3で関数から返す形にする。
        """
        spec = RunSpec(
            url=source.url,
            source_document_id=source.source_document_id,
            input_locator=source.storage_uri,
            source_hash=source.source_hash,
            input_hash=canonical_hash(input_payload),
            run_kind="extract",
            stage=stage,
            code_commit=self.code_commit,
            extractor_version=self.code_commit,  # 抽出器の論理版は未管理のため、コード版をそのまま版とする
            prompt_name=prompt_name,
            prompt_hash=prompt_file_hash(prompt_name),
            model_provider=MODEL_PROVIDER,
            model_name=LlmModel.LLM_MODEL_GEMINI.value,
            generation_config=generation_config or {},
        )
        started_at = self._now()
        try:
            result = call()
        except BaseException as exc:  # LLM関数はAPIエラー時にSystemExitを送出する
            try:
                self._append(spec, status="failed", started_at=started_at, error_code=type(exc).__name__)
            except RunPersistError as persist_error:
                logger.error(f"[Provenance] {persist_error}")
            raise
        succeeded = is_success(result)
        self._append(spec, status="succeeded" if succeeded else "failed", started_at=started_at,
                     error_code=None if succeeded else "no_result")
        return result

    def record_decision(self, *, url, stage, outcome, outcome_reason, input_payload: Mapping[str, Any]):
        """LLMを呼ばずに処理を終える判断を、成功した判断runとして残す（§4.5）。"""
        spec = RunSpec(
            url=url,
            source_document_id=None,
            input_locator=url,
            source_hash=None,
            input_hash=canonical_hash(input_payload),
            run_kind="route",
            stage=stage,
            code_commit=self.code_commit,
            extractor_version=self.code_commit,  # 抽出器の論理版は未管理のため、コード版をそのまま版とする
        )
        started_at = self._now()
        return self._append(spec, status="succeeded", started_at=started_at,
                            outcome=outcome, outcome_reason=outcome_reason)


def run_llm_stage(recorder: ProvenanceRecorder | None, source: VerifiedSource | None, *, call, **kwargs):
    """recorderがなければLLM関数をそのまま呼び、あればrunを記録して呼ぶ。"""
    if recorder is None:
        return call()
    return recorder.run_llm(source=source, call=call, **kwargs)
