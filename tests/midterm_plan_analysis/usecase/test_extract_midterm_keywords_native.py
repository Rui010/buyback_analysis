import json
from unittest.mock import MagicMock, patch

import pytest
from google.genai.errors import APIError

from midterm_plan_analysis.usecase.extract_midterm_keywords_native import (
    extract_midterm_keywords_native,
)
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
    with patch("midterm_plan_analysis.usecase.extract_midterm_keywords_native.time.sleep"):
        yield


@pytest.fixture(autouse=True)
def _no_load_dotenv():
    with patch("midterm_plan_analysis.usecase.extract_midterm_keywords_native.load_dotenv"):
        yield


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")


def _make_mock_client(response=None, side_effect=None):
    mock_client = MagicMock()
    mock_client.files.upload.return_value = MagicMock(name="uploaded-file")
    if side_effect is not None:
        mock_client.models.generate_content.side_effect = side_effect
    else:
        mock_client.models.generate_content.return_value = response
    return mock_client


class TestExtractMidtermKeywordsNative:

    def test_no_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(ValueError):
            extract_midterm_keywords_native(title="t", pdf_path="a.pdf", code="1234", name="n")

    def test_success_returns_type_and_data(self):
        mock_response = MagicMock()
        mock_response.text = VALID_JSON
        mock_client = _make_mock_client(response=mock_response)

        with patch(
            "midterm_plan_analysis.usecase.extract_midterm_keywords_native.genai.Client",
            return_value=mock_client,
        ):
            result = extract_midterm_keywords_native(title="t", pdf_path="a.pdf", code="1234", name="n")

        assert result["type"] == "MIDTERM_PLAN"
        assert result["data"]["keywords"][0]["keyword"] == "DX推進"
        assert result["data"]["keywords"][0]["context_raw"] == "全社的なDX推進により業務効率化を図る"

    def test_uploads_pdf_and_deletes_after(self):
        mock_response = MagicMock()
        mock_response.text = VALID_JSON
        mock_client = _make_mock_client(response=mock_response)

        with patch(
            "midterm_plan_analysis.usecase.extract_midterm_keywords_native.genai.Client",
            return_value=mock_client,
        ):
            extract_midterm_keywords_native(title="t", pdf_path="a.pdf", code="1234", name="n")

        mock_client.files.upload.assert_called_once()
        mock_client.files.delete.assert_called_once()

    def test_config_uses_response_schema_and_temperature(self):
        mock_response = MagicMock()
        mock_response.text = VALID_JSON
        mock_client = _make_mock_client(response=mock_response)

        with patch(
            "midterm_plan_analysis.usecase.extract_midterm_keywords_native.genai.Client",
            return_value=mock_client,
        ):
            extract_midterm_keywords_native(title="t", pdf_path="a.pdf", code="1234", name="n")

        _, kwargs = mock_client.models.generate_content.call_args
        assert kwargs["config"]["response_schema"] is MidtermKeywordExtraction
        assert kwargs["config"]["temperature"] == 0.0

    def test_json_decode_error_returns_none_after_retries(self):
        mock_response = MagicMock()
        mock_response.text = "not a json"
        mock_client = _make_mock_client(response=mock_response)

        with patch(
            "midterm_plan_analysis.usecase.extract_midterm_keywords_native.genai.Client",
            return_value=mock_client,
        ):
            result = extract_midterm_keywords_native(title="t", pdf_path="a.pdf", code="1234", name="n")

        assert result is None
        assert mock_client.models.generate_content.call_count == 3

    def test_server_error_exhausts_retries_raises_system_exit(self):
        mock_client = _make_mock_client(side_effect=APIError(503, {"error": {"message": "unavailable"}}))

        with patch(
            "midterm_plan_analysis.usecase.extract_midterm_keywords_native.genai.Client",
            return_value=mock_client,
        ):
            with pytest.raises(SystemExit):
                extract_midterm_keywords_native(title="t", pdf_path="a.pdf", code="1234", name="n")

    def test_rate_limit_error_raises_system_exit_immediately(self):
        mock_client = _make_mock_client(side_effect=APIError(429, {"error": {"message": "rate limited"}}))

        with patch(
            "midterm_plan_analysis.usecase.extract_midterm_keywords_native.genai.Client",
            return_value=mock_client,
        ):
            with pytest.raises(SystemExit):
                extract_midterm_keywords_native(title="t", pdf_path="a.pdf", code="1234", name="n")

        assert mock_client.models.generate_content.call_count == 1

    def test_unexpected_error_returns_none(self):
        mock_client = _make_mock_client(side_effect=RuntimeError("unexpected"))

        with patch(
            "midterm_plan_analysis.usecase.extract_midterm_keywords_native.genai.Client",
            return_value=mock_client,
        ):
            result = extract_midterm_keywords_native(title="t", pdf_path="a.pdf", code="1234", name="n")

        assert result is None

    def test_file_cleanup_failure_is_suppressed(self):
        """アップロード済みPDFの削除に失敗しても例外を外に伝播させない"""
        mock_response = MagicMock()
        mock_response.text = VALID_JSON
        mock_client = _make_mock_client(response=mock_response)
        mock_client.files.delete.side_effect = RuntimeError("delete failed")

        with patch(
            "midterm_plan_analysis.usecase.extract_midterm_keywords_native.genai.Client",
            return_value=mock_client,
        ):
            result = extract_midterm_keywords_native(title="t", pdf_path="a.pdf", code="1234", name="n")

        assert result["data"]["keywords"][0]["keyword"] == "DX推進"
        mock_client.files.delete.assert_called_once()
