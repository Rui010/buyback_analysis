import json
from unittest.mock import MagicMock, patch

import pytest
from google.genai.errors import APIError

from forecast_revision_analysis.usecase.extract_forecast_revision_stage1_native import (
    extract_forecast_revision_stage1_native,
)
from forecast_revision_analysis.usecase.schemas import Stage1Extraction


VALID_JSON = json.dumps(
    {
        "prev_forecast_date": "2026-02-13",
        "value_unit": "百万円",
        "periods": [],
        "reason_raw": "修正理由の原文",
    },
    ensure_ascii=False,
)


@pytest.fixture(autouse=True)
def _no_sleep():
    with patch("forecast_revision_analysis.usecase.extract_forecast_revision_stage1_native.time.sleep"):
        yield


@pytest.fixture(autouse=True)
def _no_load_dotenv():
    # .envに実際のGEMINI_API_KEYが設定されていると、load_dotenv()がmonkeypatch.delenv()後の
    # 環境変数を上書きしてしまうため、load_dotenv自体を無効化してテストを環境非依存にする
    with patch("forecast_revision_analysis.usecase.extract_forecast_revision_stage1_native.load_dotenv"):
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


class TestExtractForecastRevisionStage1Native:

    def test_no_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(ValueError):
            extract_forecast_revision_stage1_native(title="t", pdf_path="a.pdf", code="5803", name="n")

    def test_success_returns_type_and_data(self):
        mock_response = MagicMock()
        mock_response.text = VALID_JSON
        mock_client = _make_mock_client(response=mock_response)

        with patch(
            "forecast_revision_analysis.usecase.extract_forecast_revision_stage1_native.genai.Client",
            return_value=mock_client,
        ):
            result = extract_forecast_revision_stage1_native(
                title="t", pdf_path="a.pdf", code="5803", name="n"
            )

        assert result["type"] == "FORECAST_REVISION"
        assert result["data"]["reason_raw"] == "修正理由の原文"

    def test_uploads_pdf_and_deletes_after(self):
        mock_response = MagicMock()
        mock_response.text = VALID_JSON
        mock_client = _make_mock_client(response=mock_response)

        with patch(
            "forecast_revision_analysis.usecase.extract_forecast_revision_stage1_native.genai.Client",
            return_value=mock_client,
        ):
            extract_forecast_revision_stage1_native(title="t", pdf_path="a.pdf", code="5803", name="n")

        mock_client.files.upload.assert_called_once()
        mock_client.files.delete.assert_called_once()

    def test_config_uses_response_schema(self):
        mock_response = MagicMock()
        mock_response.text = VALID_JSON
        mock_client = _make_mock_client(response=mock_response)

        with patch(
            "forecast_revision_analysis.usecase.extract_forecast_revision_stage1_native.genai.Client",
            return_value=mock_client,
        ):
            extract_forecast_revision_stage1_native(title="t", pdf_path="a.pdf", code="5803", name="n")

        _, kwargs = mock_client.models.generate_content.call_args
        assert kwargs["config"]["response_schema"] is Stage1Extraction

    def test_json_decode_error_returns_none_after_retries(self):
        mock_response = MagicMock()
        mock_response.text = "not a json"
        mock_client = _make_mock_client(response=mock_response)

        with patch(
            "forecast_revision_analysis.usecase.extract_forecast_revision_stage1_native.genai.Client",
            return_value=mock_client,
        ):
            result = extract_forecast_revision_stage1_native(
                title="t", pdf_path="a.pdf", code="5803", name="n"
            )

        assert result is None
        assert mock_client.models.generate_content.call_count == 3

    def test_server_error_exhausts_retries_raises_system_exit(self):
        mock_client = _make_mock_client(side_effect=APIError(503, {"error": {"message": "unavailable"}}))

        with patch(
            "forecast_revision_analysis.usecase.extract_forecast_revision_stage1_native.genai.Client",
            return_value=mock_client,
        ):
            with pytest.raises(SystemExit):
                extract_forecast_revision_stage1_native(title="t", pdf_path="a.pdf", code="5803", name="n")

    def test_rate_limit_error_raises_system_exit_immediately(self):
        mock_client = _make_mock_client(side_effect=APIError(429, {"error": {"message": "rate limited"}}))

        with patch(
            "forecast_revision_analysis.usecase.extract_forecast_revision_stage1_native.genai.Client",
            return_value=mock_client,
        ):
            with pytest.raises(SystemExit):
                extract_forecast_revision_stage1_native(title="t", pdf_path="a.pdf", code="5803", name="n")

        assert mock_client.models.generate_content.call_count == 1

    def test_unexpected_error_returns_none(self):
        mock_client = _make_mock_client(side_effect=RuntimeError("unexpected"))

        with patch(
            "forecast_revision_analysis.usecase.extract_forecast_revision_stage1_native.genai.Client",
            return_value=mock_client,
        ):
            result = extract_forecast_revision_stage1_native(
                title="t", pdf_path="a.pdf", code="5803", name="n"
            )

        assert result is None

    def test_file_cleanup_failure_is_suppressed(self):
        """アップロード済みPDFの削除に失敗しても例外を外に伝播させない"""
        mock_response = MagicMock()
        mock_response.text = VALID_JSON
        mock_client = _make_mock_client(response=mock_response)
        mock_client.files.delete.side_effect = RuntimeError("delete failed")

        with patch(
            "forecast_revision_analysis.usecase.extract_forecast_revision_stage1_native.genai.Client",
            return_value=mock_client,
        ):
            result = extract_forecast_revision_stage1_native(
                title="t", pdf_path="a.pdf", code="5803", name="n"
            )

        assert result["data"]["reason_raw"] == "修正理由の原文"
        mock_client.files.delete.assert_called_once()

    def test_lead_text_extraction_failure_falls_back_to_placeholder(self):
        """存在しないpdf_pathでも例外を出さず、プロンプトにフォールバック文言を埋め込んで続行する"""
        mock_response = MagicMock()
        mock_response.text = VALID_JSON
        mock_client = _make_mock_client(response=mock_response)

        with patch(
            "forecast_revision_analysis.usecase.extract_forecast_revision_stage1_native.genai.Client",
            return_value=mock_client,
        ), patch(
            "forecast_revision_analysis.usecase.extract_forecast_revision_stage1_native.load_prompt_template"
        ) as mock_load_prompt:
            mock_load_prompt.return_value = "prompt"
            extract_forecast_revision_stage1_native(
                title="t", pdf_path="not_exist.pdf", code="5803", name="n"
            )

        _, kwargs = mock_load_prompt.call_args
        assert kwargs["lead_text"] == "（抽出できませんでした）"

    def test_lead_text_extracted_from_first_page_is_passed_to_prompt(self):
        """PDF1ページ目冒頭のテキストがlead_textとしてプロンプトに渡される"""
        mock_response = MagicMock()
        mock_response.text = VALID_JSON
        mock_client = _make_mock_client(response=mock_response)

        mock_reader = MagicMock()
        mock_reader.is_encrypted = False
        mock_reader.pages = [MagicMock(extract_text=lambda: "2025年10月31日に公表した業績予想を修正")]

        with patch(
            "forecast_revision_analysis.usecase.extract_forecast_revision_stage1_native.genai.Client",
            return_value=mock_client,
        ), patch(
            "forecast_revision_analysis.usecase.extract_forecast_revision_stage1_native.PdfReader",
            return_value=mock_reader,
        ), patch("builtins.open", MagicMock()), patch(
            "forecast_revision_analysis.usecase.extract_forecast_revision_stage1_native.load_prompt_template"
        ) as mock_load_prompt:
            mock_load_prompt.return_value = "prompt"
            extract_forecast_revision_stage1_native(
                title="t", pdf_path="a.pdf", code="5803", name="n"
            )

        _, kwargs = mock_load_prompt.call_args
        assert kwargs["lead_text"] == "2025年10月31日に公表した業績予想を修正"
