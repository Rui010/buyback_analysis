import json
from unittest.mock import MagicMock, patch

import pytest
from google.genai.errors import APIError

from midterm_plan_analysis.usecase.extract_midterm_keywords import extract_midterm_keywords
from midterm_plan_analysis.usecase.schemas import MidtermKeywordExtraction


VALID_JSON = json.dumps(
    {
        "keywords": [
            {"keyword": "DX推進", "context_raw": "全社的なDX推進により業務効率化を図る"},
            {"keyword": "海外展開", "context_raw": "東南アジア地域への事業展開を加速する"},
        ]
    },
    ensure_ascii=False,
)


@pytest.fixture(autouse=True)
def _no_sleep():
    with patch("midterm_plan_analysis.usecase.extract_midterm_keywords.time.sleep"):
        yield


@pytest.fixture(autouse=True)
def _no_load_dotenv():
    # .envに実際のGEMINI_API_KEYが設定されていると、load_dotenv()がmonkeypatch.delenv()後の
    # 環境変数を上書きしてしまうため、load_dotenv自体を無効化してテストを環境非依存にする
    with patch("midterm_plan_analysis.usecase.extract_midterm_keywords.load_dotenv"):
        yield


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")


class TestExtractMidtermKeywords:

    def test_no_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(ValueError):
            extract_midterm_keywords(title="t", content="c", code="1234", name="n")

    def test_success_returns_type_and_data(self):
        mock_response = MagicMock()
        mock_response.text = VALID_JSON
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with patch(
            "midterm_plan_analysis.usecase.extract_midterm_keywords.genai.Client",
            return_value=mock_client,
        ):
            result = extract_midterm_keywords(title="t", content="c", code="1234", name="n")

        assert result["type"] == "MIDTERM_PLAN"
        assert result["data"]["keywords"][0]["keyword"] == "DX推進"
        assert result["data"]["keywords"][0]["context_raw"] == "全社的なDX推進により業務効率化を図る"

    def test_config_uses_response_schema_and_temperature(self):
        mock_response = MagicMock()
        mock_response.text = VALID_JSON
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with patch(
            "midterm_plan_analysis.usecase.extract_midterm_keywords.genai.Client",
            return_value=mock_client,
        ):
            extract_midterm_keywords(title="t", content="c", code="1234", name="n")

        _, kwargs = mock_client.models.generate_content.call_args
        assert kwargs["config"]["response_schema"] is MidtermKeywordExtraction
        assert kwargs["config"]["response_mime_type"] == "application/json"
        assert kwargs["config"]["temperature"] == 0.0

    def test_json_decode_error_returns_none_after_retries(self):
        mock_response = MagicMock()
        mock_response.text = "not a json"
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with patch(
            "midterm_plan_analysis.usecase.extract_midterm_keywords.genai.Client",
            return_value=mock_client,
        ):
            result = extract_midterm_keywords(title="t", content="c", code="1234", name="n")

        assert result is None
        assert mock_client.models.generate_content.call_count == 3

    def test_server_error_exhausts_retries_raises_system_exit(self):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = APIError(
            503, {"error": {"message": "unavailable"}}
        )

        with patch(
            "midterm_plan_analysis.usecase.extract_midterm_keywords.genai.Client",
            return_value=mock_client,
        ):
            with pytest.raises(SystemExit):
                extract_midterm_keywords(title="t", content="c", code="1234", name="n")

    def test_rate_limit_error_raises_system_exit_immediately(self):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = APIError(
            429, {"error": {"message": "rate limited"}}
        )

        with patch(
            "midterm_plan_analysis.usecase.extract_midterm_keywords.genai.Client",
            return_value=mock_client,
        ):
            with pytest.raises(SystemExit):
                extract_midterm_keywords(title="t", content="c", code="1234", name="n")

        assert mock_client.models.generate_content.call_count == 1

    def test_unexpected_error_returns_none(self):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError("unexpected")

        with patch(
            "midterm_plan_analysis.usecase.extract_midterm_keywords.genai.Client",
            return_value=mock_client,
        ):
            result = extract_midterm_keywords(title="t", content="c", code="1234", name="n")

        assert result is None
