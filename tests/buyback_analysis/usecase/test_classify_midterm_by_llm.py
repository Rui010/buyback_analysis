import json
import pytest
from unittest.mock import MagicMock, patch

from buyback_analysis.usecase.classify_midterm_by_llm import classify_midterm_by_llm


def _make_response(status: str) -> MagicMock:
    mock = MagicMock()
    mock.text = json.dumps({"extraction_status": status})
    return mock


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")


class TestClassifyMidtermByLlm:

    def _call(self, status: str) -> str:
        with patch("buyback_analysis.usecase.classify_midterm_by_llm.genai.Client") as mock_client, \
             patch("buyback_analysis.usecase.classify_midterm_by_llm.time.sleep"):
            mock_client.return_value.models.generate_content.return_value = _make_response(status)
            return classify_midterm_by_llm(
                title="テスト", content="本文", code="1234", name="テスト株式会社"
            )

    def test_withdrawn_is_returned(self):
        assert self._call("withdrawn") == "withdrawn"

    def test_no_targets_is_returned(self):
        assert self._call("no_targets") == "no_targets"

    def test_postponed_is_returned(self):
        assert self._call("postponed") == "postponed"

    def test_unknown_status_returns_failed(self):
        assert self._call("unknown_value") == "failed"

    def test_json_decode_error_returns_failed(self):
        with patch("buyback_analysis.usecase.classify_midterm_by_llm.genai.Client") as mock_client, \
             patch("buyback_analysis.usecase.classify_midterm_by_llm.time.sleep"):
            bad = MagicMock()
            bad.text = "not json"
            mock_client.return_value.models.generate_content.return_value = bad
            result = classify_midterm_by_llm(
                title="テスト", content="本文", code="1234", name="テスト株式会社"
            )
        assert result == "failed"
