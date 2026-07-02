import json
from unittest.mock import MagicMock, patch

import pytest
from google.genai.errors import APIError

from forecast_revision_analysis.usecase.infer_forecast_revision_stage2 import (
    infer_forecast_revision_stage2,
)
from forecast_revision_analysis.usecase.schemas import Stage2Inference


VALID_JSON = json.dumps(
    {
        "direct_factors": ["受注増加"],
        "structural_vulnerability": ["光ファイバへの依存"],
        "spillover_conditions": ["光ケーブルメーカー"],
    },
    ensure_ascii=False,
)


@pytest.fixture(autouse=True)
def _no_sleep():
    with patch("forecast_revision_analysis.usecase.infer_forecast_revision_stage2.time.sleep"):
        yield


@pytest.fixture(autouse=True)
def _no_load_dotenv():
    # .envに実際のGEMINI_API_KEYが設定されていると、load_dotenv()がmonkeypatch.delenv()後の
    # 環境変数を上書きしてしまうため、load_dotenv自体を無効化してテストを環境非依存にする
    with patch("forecast_revision_analysis.usecase.infer_forecast_revision_stage2.load_dotenv"):
        yield


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")


class TestInferForecastRevisionStage2:

    def test_no_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(ValueError):
            infer_forecast_revision_stage2(context="dummy context")

    def test_success_returns_type_and_data(self):
        mock_response = MagicMock()
        mock_response.text = VALID_JSON
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with patch(
            "forecast_revision_analysis.usecase.infer_forecast_revision_stage2.genai.Client",
            return_value=mock_client,
        ):
            result = infer_forecast_revision_stage2(context="dummy context")

        assert result["type"] == "FORECAST_REVISION"
        assert result["data"]["direct_factors"] == ["受注増加"]

    def test_config_uses_response_schema_and_temperature(self):
        mock_response = MagicMock()
        mock_response.text = VALID_JSON
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with patch(
            "forecast_revision_analysis.usecase.infer_forecast_revision_stage2.genai.Client",
            return_value=mock_client,
        ):
            infer_forecast_revision_stage2(context="dummy context")

        _, kwargs = mock_client.models.generate_content.call_args
        assert kwargs["config"]["response_schema"] is Stage2Inference
        assert kwargs["config"]["response_mime_type"] == "application/json"
        assert kwargs["config"]["temperature"] == 0.2

    def test_json_decode_error_returns_none_after_retries(self):
        mock_response = MagicMock()
        mock_response.text = "not a json"
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with patch(
            "forecast_revision_analysis.usecase.infer_forecast_revision_stage2.genai.Client",
            return_value=mock_client,
        ):
            result = infer_forecast_revision_stage2(context="dummy context")

        assert result is None
        assert mock_client.models.generate_content.call_count == 3

    def test_server_error_exhausts_retries_raises_system_exit(self):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = APIError(
            503, {"error": {"message": "unavailable"}}
        )

        with patch(
            "forecast_revision_analysis.usecase.infer_forecast_revision_stage2.genai.Client",
            return_value=mock_client,
        ):
            with pytest.raises(SystemExit):
                infer_forecast_revision_stage2(context="dummy context")

    def test_rate_limit_error_raises_system_exit_immediately(self):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = APIError(
            429, {"error": {"message": "rate limited"}}
        )

        with patch(
            "forecast_revision_analysis.usecase.infer_forecast_revision_stage2.genai.Client",
            return_value=mock_client,
        ):
            with pytest.raises(SystemExit):
                infer_forecast_revision_stage2(context="dummy context")

        assert mock_client.models.generate_content.call_count == 1

    def test_unexpected_error_returns_none(self):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError("unexpected")

        with patch(
            "forecast_revision_analysis.usecase.infer_forecast_revision_stage2.genai.Client",
            return_value=mock_client,
        ):
            result = infer_forecast_revision_stage2(context="dummy context")

        assert result is None
