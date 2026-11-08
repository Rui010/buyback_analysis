"""LLM呼び出しのtoken数・request IDを、LLM関数の戻り値を変えずに受け取る仕組み。

LLM関数はgenerate_content()の直後にreport_llm_response(response)を呼ぶ。
capture_llm_usage()の中で呼ばれた分だけが集計され、外では何もしない
（自己株買いなど、run記録をしない経路には影響しない）。
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class LlmUsage:
    input_tokens: int = 0
    output_tokens: int = 0  # 回答token + 思考token（thoughts_token_count）
    request_ids: list[str] = field(default_factory=list)

    @property
    def last_request_id(self) -> str | None:
        return self.request_ids[-1] if self.request_ids else None


_current: ContextVar[LlmUsage | None] = ContextVar("llm_usage", default=None)


@contextmanager
def capture_llm_usage():
    usage = LlmUsage()
    token = _current.set(usage)
    try:
        yield usage
    finally:
        _current.reset(token)


def report_llm_response(response) -> None:
    """generate_content()の応答から使用量を加算する。リトライで複数回成功応答があれば合計する。"""
    usage = _current.get()
    if usage is None:
        return
    metadata = getattr(response, "usage_metadata", None)
    if metadata is not None:
        usage.input_tokens += getattr(metadata, "prompt_token_count", None) or 0
        usage.output_tokens += (getattr(metadata, "candidates_token_count", None) or 0) + (
            getattr(metadata, "thoughts_token_count", None) or 0
        )
    response_id = getattr(response, "response_id", None)
    if response_id:
        usage.request_ids.append(response_id)
