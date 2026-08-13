"""Tests for ElevenLabsProvider: contract, error mapping, temp-file writing.

No test here ever calls the real ElevenLabs API — a fake client
(matching the shape of ``elevenlabs.client.ElevenLabs.text_to_speech``)
is injected via the ``client_factory`` constructor argument.
"""

from __future__ import annotations

import httpx
import pytest
from elevenlabs.core.api_error import ApiError
from elevenlabs.errors import ForbiddenError, UnauthorizedError

from app.core.ai.exceptions import (
    ProviderAuthenticationError,
    ProviderMalformedResponseError,
    ProviderNetworkError,
    ProviderNotConfiguredError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderTimeoutError,
)
from app.core.ai.provider_interface import GenerationRequest
from app.core.ai.providers.elevenlabs_provider import (
    DEFAULT_MODEL,
    ElevenLabsProvider,
    _sanitize_error_detail,
)


class _FakeTextToSpeech:
    def __init__(self, chunks: list[bytes] | None = None, exception: Exception | None = None) -> None:
        self._chunks = chunks if chunks is not None else [b"RIFF....WAVEfake"]
        self._exception = exception
        self.calls: list[dict[str, object]] = []

    def convert(self, voice_id, *, text, model_id, output_format, voice_settings):
        self.calls.append(
            {
                "voice_id": voice_id,
                "text": text,
                "model_id": model_id,
                "output_format": output_format,
                "voice_settings": voice_settings,
            }
        )
        if self._exception is not None:
            raise self._exception
        return iter(self._chunks)


class _FakeClient:
    def __init__(self, text_to_speech: _FakeTextToSpeech) -> None:
        self.text_to_speech = text_to_speech


def _provider(tts: _FakeTextToSpeech, **kwargs) -> ElevenLabsProvider:
    return ElevenLabsProvider(
        api_key=kwargs.pop("api_key", "fake-api-key"),
        client_factory=lambda api_key: _FakeClient(tts),
        **kwargs,
    )


def _request(**overrides) -> GenerationRequest:
    defaults = {"modality": "voice", "prompt_text": "مرحباً", "parameters": {"voice_id": "voice-abc"}}
    defaults.update(overrides)
    return GenerationRequest(**defaults)


# --- configuration -----------------------------------------------------------


def test_is_configured_true_with_explicit_api_key() -> None:
    assert ElevenLabsProvider(api_key="key").is_configured() is True


def test_is_configured_false_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    assert ElevenLabsProvider(api_key=None).is_configured() is False


def test_model_defaults_to_default_model_constant() -> None:
    assert ElevenLabsProvider(api_key="key").model == DEFAULT_MODEL


def test_model_explicit_argument_overrides_default() -> None:
    assert ElevenLabsProvider(api_key="key", model="eleven_v3").model == "eleven_v3"


def test_model_reads_env_var_when_not_passed_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELEVENLABS_VOICE_MODEL", "eleven_flash_v2_5")
    assert ElevenLabsProvider(api_key="key").model == "eleven_flash_v2_5"


def test_generate_raises_not_configured_when_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    provider = ElevenLabsProvider(api_key=None, client_factory=lambda api_key: _FakeClient(_FakeTextToSpeech()))
    with pytest.raises(ProviderNotConfiguredError):
        provider.generate(_request())


def test_generate_rejects_unsupported_modality() -> None:
    provider = _provider(_FakeTextToSpeech())
    with pytest.raises(ValueError, match="does not support modality"):
        provider.generate(_request(modality="image"))


def test_generate_requires_voice_id_parameter() -> None:
    provider = _provider(_FakeTextToSpeech())
    with pytest.raises(ProviderRequestError, match="voice_id"):
        provider.generate(_request(parameters={}))


# --- success path --------------------------------------------------------------


def test_generate_success_writes_temp_wav_file() -> None:
    tts = _FakeTextToSpeech(chunks=[b"real ", b"wav ", b"bytes"])
    provider = _provider(tts, model="eleven_multilingual_v2")

    result = provider.generate(_request())

    assert result.provider_name == "elevenlabs"
    assert result.output_path.is_file()
    assert result.output_path.read_bytes() == b"real wav bytes"
    assert result.output_path.suffix == ".wav"
    assert "eleven_multilingual_v2" in result.raw_response_summary


def test_generate_sends_prompt_text_and_voice_id() -> None:
    tts = _FakeTextToSpeech()
    provider = _provider(tts)

    provider.generate(_request(prompt_text="أهلاً وسهلاً", parameters={"voice_id": "voice-xyz"}))

    assert tts.calls[0]["text"] == "أهلاً وسهلاً"
    assert tts.calls[0]["voice_id"] == "voice-xyz"


def test_generate_defaults_output_format_to_wav() -> None:
    tts = _FakeTextToSpeech()
    provider = _provider(tts)

    provider.generate(_request())

    assert tts.calls[0]["output_format"] == "wav_44100"


def test_generate_builds_voice_settings_from_known_parameters() -> None:
    tts = _FakeTextToSpeech()
    provider = _provider(tts)

    provider.generate(
        _request(parameters={"voice_id": "v1", "stability": 0.5, "style": 0.2, "unknown_key": "ignored"})
    )

    settings = tts.calls[0]["voice_settings"]
    assert settings is not None
    assert settings.stability == 0.5
    assert settings.style == 0.2


def test_generate_voice_settings_none_when_no_known_keys() -> None:
    tts = _FakeTextToSpeech()
    provider = _provider(tts)

    provider.generate(_request(parameters={"voice_id": "v1"}))

    assert tts.calls[0]["voice_settings"] is None


# --- error mapping ---------------------------------------------------------


def test_generate_maps_401_to_authentication_error() -> None:
    tts = _FakeTextToSpeech(exception=UnauthorizedError(body="unauthorized"))
    provider = _provider(tts)
    with pytest.raises(ProviderAuthenticationError):
        provider.generate(_request())


def test_generate_maps_403_to_authentication_error() -> None:
    tts = _FakeTextToSpeech(exception=ForbiddenError(body="forbidden"))
    provider = _provider(tts)
    with pytest.raises(ProviderAuthenticationError):
        provider.generate(_request())


def test_generate_401_includes_sanitized_missing_permission_detail() -> None:
    """A real 401 body (as observed from ElevenLabs) must surface its
    type/code/message/status in the raised exception's message, so a
    scoped API key's exact missing permission is diagnosable without a
    second manual probe."""
    body = {
        "detail": {
            "type": "authentication_error",
            "code": "unauthorized",
            "message": "The API key you used is missing the permission text_to_speech to execute this operation.",
            "status": "missing_permissions",
            "request_id": "req-should-not-appear-verbatim-as-a-key",
        }
    }
    tts = _FakeTextToSpeech(exception=UnauthorizedError(body=body))
    provider = _provider(tts)
    with pytest.raises(ProviderAuthenticationError) as exc_info:
        provider.generate(_request())
    message = str(exc_info.value)
    assert "authentication failed (401)" in message
    assert "type=authentication_error" in message
    assert "code=unauthorized" in message
    assert "status=missing_permissions" in message
    assert "missing the permission text_to_speech" in message


def test_generate_403_includes_sanitized_missing_permission_detail() -> None:
    body = {
        "detail": {
            "type": "authentication_error",
            "code": "unauthorized",
            "message": "The API key you used is missing the permission voices_read to execute this operation.",
            "status": "missing_permissions",
        }
    }
    tts = _FakeTextToSpeech(exception=ForbiddenError(body=body))
    provider = _provider(tts)
    with pytest.raises(ProviderAuthenticationError) as exc_info:
        provider.generate(_request())
    message = str(exc_info.value)
    assert "authentication failed (403)" in message
    assert "status=missing_permissions" in message
    assert "missing the permission voices_read" in message


def test_generate_401_without_structured_body_keeps_plain_message() -> None:
    """Backward compatible: a plain-string body (no "detail" dict) must
    not crash and must not fabricate any detail suffix."""
    tts = _FakeTextToSpeech(exception=UnauthorizedError(body="unauthorized"))
    provider = _provider(tts)
    with pytest.raises(ProviderAuthenticationError) as exc_info:
        provider.generate(_request())
    assert str(exc_info.value) == "ElevenLabs authentication failed (401)."


def test_generate_401_never_exposes_headers_or_authorization_values() -> None:
    body = {
        "detail": {
            "type": "authentication_error",
            "code": "unauthorized",
            "message": "missing permission",
            "status": "missing_permissions",
        }
    }
    secret_headers = {
        "Authorization": "Bearer sk_should_never_appear_anywhere",
        "xi-api-key": "sk_also_never_appear",
    }
    tts = _FakeTextToSpeech(exception=UnauthorizedError(body=body, headers=secret_headers))
    provider = _provider(tts, api_key="sk_the_real_configured_key_must_not_leak")
    with pytest.raises(ProviderAuthenticationError) as exc_info:
        provider.generate(_request())
    message = str(exc_info.value)
    assert "sk_should_never_appear_anywhere" not in message
    assert "sk_also_never_appear" not in message
    assert "sk_the_real_configured_key_must_not_leak" not in message
    assert "Authorization" not in message
    assert "xi-api-key" not in message


# --- _sanitize_error_detail unit tests --------------------------------------


def test_sanitize_error_detail_extracts_only_allowlisted_fields() -> None:
    body = {
        "detail": {
            "type": "authentication_error",
            "code": "unauthorized",
            "message": "missing permission",
            "status": "missing_permissions",
            "request_id": "req-123",
            "api_key": "sk_should_never_be_read",
            "authorization": "Bearer sk_should_never_be_read_either",
        }
    }
    result = _sanitize_error_detail(body)
    assert result is not None
    assert "type=authentication_error" in result
    assert "code=unauthorized" in result
    assert "message=missing permission" in result
    assert "status=missing_permissions" in result
    assert "req-123" not in result
    assert "sk_should_never_be_read" not in result
    assert "sk_should_never_be_read_either" not in result


def test_sanitize_error_detail_returns_none_without_detail_key() -> None:
    assert _sanitize_error_detail({"message": "top-level, not nested under detail"}) is None


def test_sanitize_error_detail_returns_none_when_detail_is_not_a_dict() -> None:
    assert _sanitize_error_detail({"detail": "just a string"}) is None


def test_sanitize_error_detail_returns_none_for_non_dict_body() -> None:
    assert _sanitize_error_detail("plain string body") is None
    assert _sanitize_error_detail(None) is None


def test_generate_maps_429_to_rate_limit_error() -> None:
    tts = _FakeTextToSpeech(exception=ApiError(status_code=429, body="rate limited"))
    provider = _provider(tts)
    with pytest.raises(ProviderRateLimitError):
        provider.generate(_request())


def test_generate_maps_generic_api_error_to_provider_request_error() -> None:
    tts = _FakeTextToSpeech(exception=ApiError(status_code=400, body="bad request"))
    provider = _provider(tts)
    with pytest.raises(ProviderRequestError):
        provider.generate(_request())


def test_generate_maps_timeout_to_provider_timeout_error() -> None:
    tts = _FakeTextToSpeech(exception=TimeoutError("timed out"))
    provider = _provider(tts)
    with pytest.raises(ProviderTimeoutError):
        provider.generate(_request())


def test_generate_maps_empty_response_to_malformed_response_error() -> None:
    tts = _FakeTextToSpeech(chunks=[])
    provider = _provider(tts)
    with pytest.raises(ProviderMalformedResponseError):
        provider.generate(_request())


def test_generate_maps_network_error() -> None:
    tts = _FakeTextToSpeech(exception=httpx.ConnectError("connection failed"))
    provider = _provider(tts)
    with pytest.raises(ProviderNetworkError):
        provider.generate(_request())
