from buyback_analysis.usecase.parse_text_by_llm import _sanitize_null_strings


class TestSanitizeNullStrings:
    def test_string_null_converted_to_none(self):
        assert _sanitize_null_strings("null") is None

    def test_non_null_string_unchanged(self):
        assert _sanitize_null_strings("hello") == "hello"

    def test_dict_values_sanitized(self):
        result = _sanitize_null_strings({"code": "null", "name": "テスト"})
        assert result == {"code": None, "name": "テスト"}

    def test_nested_dict_sanitized(self):
        result = _sanitize_null_strings({"data": {"code": "null", "amount": "null"}})
        assert result == {"data": {"code": None, "amount": None}}

    def test_list_values_sanitized(self):
        result = _sanitize_null_strings(["null", "value", "null"])
        assert result == [None, "value", None]

    def test_none_unchanged(self):
        assert _sanitize_null_strings(None) is None

    def test_integer_unchanged(self):
        assert _sanitize_null_strings(123) == 123
