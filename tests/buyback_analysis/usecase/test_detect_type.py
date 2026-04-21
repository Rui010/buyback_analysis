from unittest.mock import MagicMock, patch
from buyback_analysis.usecase.detect_type import detect_type_by_llm


class TestDetectTypeByLlm:
    def _make_response(self, text: str):
        response = MagicMock()
        response.text = text
        return response

    def _call(self, response_text: str) -> str:
        with patch("buyback_analysis.usecase.detect_type.genai.Client") as mock_client:
            mock_client.return_value.models.generate_content.return_value = self._make_response(response_text)
            return detect_type_by_llm("タイトル", "本文")

    def test_valid_label_returned(self):
        assert self._call("buyback_announcement") == "buyback_announcement"

    def test_other_returned_as_other(self):
        assert self._call("other") == "other"

    def test_invalid_label_falls_back_to_other(self):
        assert self._call("other（理由：不明）") == "other"

    def test_empty_string_falls_back_to_other(self):
        assert self._call("") == "other"
