import httpx
import pytest
from unittest.mock import MagicMock, patch
from google import genai
from google.genai.errors import APIError
from forecast_revision_analysis.usecase.post_forecast_revision import check_missing_fields


def test_missing_details_preserve_code_url_and_field():
    details = []
    assert check_missing_fields({'data': {'periods': []}}, '3512', 'source', details=details)
    assert details == ['[MISSING] field=prev_forecast_date code=3512 url=source']


@pytest.mark.parametrize('status', [429, 503])
def test_real_sdk_upload_checks_http_error_before_file_key(tmp_path, status):
    from forecast_revision_analysis.usecase.extract_forecast_revision_stage1_native import _check_http_response
    pdf = tmp_path / 'test.pdf'
    pdf.write_bytes(b'%PDF-1.4 test')
    def respond(request):
        if request.url.path == '/upload/v1beta/files':
            return httpx.Response(200, headers={'x-goog-upload-url': 'https://example.test/upload'})
        return httpx.Response(status, headers={'x-goog-upload-status': 'final'}, json={'error': {'message': 'test error'}})
    client = genai.Client(api_key='dummy', http_options={'client_args': {
        'transport': httpx.MockTransport(respond), 'event_hooks': {'response': [_check_http_response]}}})
    with pytest.raises(APIError) as caught:
        client.files.upload(file=str(pdf), config={'mime_type': 'application/pdf'})
    assert caught.value.code == status


def test_success_response_is_not_consumed():
    from forecast_revision_analysis.usecase.extract_forecast_revision_stage1_native import _check_http_response
    _check_http_response(httpx.Response(200, json={'file': {'name': 'files/test'}}))


def test_upload_429_stops_pipeline_and_logs_code(monkeypatch):
    from forecast_revision_analysis.usecase.extract_forecast_revision_stage1_native import (
        extract_forecast_revision_stage1_native, _check_http_response,
    )
    monkeypatch.setenv('GEMINI_API_KEY', 'dummy')
    client = MagicMock()
    client.files.upload.side_effect = APIError(429, {'error': {'message': 'monthly cap'}})
    module = 'forecast_revision_analysis.usecase.extract_forecast_revision_stage1_native'
    with patch(module + '.genai.Client', return_value=client) as factory, patch(module + '.logger') as logger:
        with pytest.raises(SystemExit, match='HTTP 429'):
            extract_forecast_revision_stage1_native('title', 'missing.pdf', '3512', 'name')
    assert factory.call_args.kwargs['http_options']['client_args']['event_hooks']['response'] == [_check_http_response]
    client.models.generate_content.assert_not_called()
    client.files.delete.assert_not_called()
    assert 'HTTP 429 code=3512' in logger.error.call_args.args[0]
