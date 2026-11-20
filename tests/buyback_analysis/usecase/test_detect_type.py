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


class TestGetParseStatusInDb:
    def _session(self, record):
        session = MagicMock()
        session.query.return_value.filter_by.return_value.first.return_value = record
        return session

    def test_returns_status_of_existing_record(self):
        from buyback_analysis.usecase.detect_type import get_parse_status_in_db

        record = MagicMock(parse_status="skipped")
        assert get_parse_status_in_db(self._session(record), "https://example.test/a.pdf") == "skipped"

    def test_returns_none_when_record_missing(self):
        from buyback_analysis.usecase.detect_type import get_parse_status_in_db

        assert get_parse_status_in_db(self._session(None), "https://example.test/a.pdf") is None

    def test_returns_none_on_db_error(self):
        from buyback_analysis.usecase.detect_type import get_parse_status_in_db

        session = MagicMock()
        session.query.side_effect = RuntimeError("database is locked")
        assert get_parse_status_in_db(session, "https://example.test/a.pdf") is None
