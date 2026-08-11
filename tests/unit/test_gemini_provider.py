"""Tests for GeminiProvider: contract, error mapping, temp-file writing.

No test here ever calls the real Gemini API — a fake client (matching
the shape of ``google.genai.Client.models.generate_content``) is
injected via the ``client_factory`` constructor argument. See
``docs/`` Milestone 7 status for the one, deliberately minimal, manual
real-API verification performed separately (not part of the automated
suite).
"""

from __future__ import annotations

import httpx
import pytest
from google.genai import errors as genai_errors

from app.core.ai.exceptions import (
    ProviderMalformedResponseError,
    ProviderNetworkError,
    ProviderNotConfiguredError,
    ProviderRateLimitError,
    ProviderRejectionError,
    ProviderRequestError,
    ProviderTimeoutError,
)
from app.core.ai.provider_interface import GenerationRequest
from app.core.ai.providers.gemini_provider import DEFAULT_MODEL, GeminiProvider


class _FakeBlob:
    def __init__(self, data: bytes | None, mime_type: str | None) -> None:
        self.data = data
        self.mime_type = mime_type


class _FakePart:
    def __init__(self, data: bytes | None = None, mime_type: str | None = None) -> None:
        self.inline_data = _FakeBlob(data, mime_type) if data is not None else None


class _FakeContent:
    def __init__(self, parts: list[_FakePart] | None) -> None:
        self.parts = parts


class _FakeCandidate:
    def __init__(self, parts: list[_FakePart] | None, finish_reason: str | None = "STOP") -> None:
        self.content = _FakeContent(parts) if parts is not None else None
        self.finish_reason = finish_reason


class _FakePromptFeedback:
    def __init__(self, block_reason: str | None, block_reason_message: str | None = None) -> None:
        self.block_reason = block_reason
        self.block_reason_message = block_reason_message


class _FakeResponse:
    def __init__(self, candidates=None, prompt_feedback=None) -> None:
        self.candidates = candidates if candidates is not None else []
        self.prompt_feedback = prompt_feedback


class _FakeModels:
    def __init__(self, response=None, exception: Exception | None = None) -> None:
        self._response = response
        self._exception = exception
        self.calls: list[dict[str, object]] = []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self._exception is not None:
            raise self._exception
        return self._response


class _FakeClient:
    def __init__(self, models: _FakeModels) -> None:
        self.models = models


def _provider(models: _FakeModels, **kwargs) -> GeminiProvider:
    return GeminiProvider(
        api_key=kwargs.pop("api_key", "fake-api-key"),
        client_factory=lambda api_key: _FakeClient(models),
        **kwargs,
    )


def _success_response(data: bytes = b"fake-image-bytes", mime_type: str = "image/png") -> _FakeResponse:
    return _FakeResponse(candidates=[_FakeCandidate([_FakePart(data=data, mime_type=mime_type)])])


# --- configuration -------------------------------------------------------


def test_is_configured_true_with_explicit_api_key() -> None:
    assert GeminiProvider(api_key="key").is_configured() is True


def test_is_configured_false_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert GeminiProvider(api_key=None).is_configured() is False


def test_model_defaults_to_default_model_constant() -> None:
    assert GeminiProvider(api_key="key").model == DEFAULT_MODEL


def test_model_explicit_argument_overrides_default() -> None:
    assert GeminiProvider(api_key="key", model="gemini-3-pro-image").model == "gemini-3-pro-image"


def test_model_reads_env_var_when_not_passed_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOS_GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
    assert GeminiProvider(api_key="key").model == "gemini-2.5-flash-image"


def test_generate_raises_not_configured_when_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # api_key=None means "fall back to the GEMINI_API_KEY env var" (the
    # documented, intentional behavior GeminiProvider.__init__ uses for its
    # zero-arg PROVIDER_REGISTRY construction) -- so this test must clear
    # the env var itself to actually exercise the "not configured" path,
    # rather than relying on the ambient environment happening to have no
    # real key set.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    provider = GeminiProvider(api_key=None, client_factory=lambda api_key: _FakeClient(_FakeModels()))
    with pytest.raises(ProviderNotConfiguredError):
        provider.generate(GenerationRequest(modality="image", prompt_text="x"))


def test_generate_rejects_unsupported_modality() -> None:
    provider = _provider(_FakeModels())
    with pytest.raises(ValueError, match="does not support modality"):
        provider.generate(GenerationRequest(modality="voice", prompt_text="x"))


# --- success path ----------------------------------------------------------


def test_generate_success_writes_temp_file_and_returns_result() -> None:
    models = _FakeModels(response=_success_response(data=b"real bytes here"))
    provider = _provider(models, model="gemini-3.1-flash-image")

    result = provider.generate(GenerationRequest(modality="image", prompt_text="a cat"))

    assert result.provider_name == "gemini"
    assert result.output_path.is_file()
    assert result.output_path.read_bytes() == b"real bytes here"
    assert result.output_path.suffix == ".png"
    assert "gemini-3.1-flash-image" in result.raw_response_summary
    assert models.calls[0]["model"] == "gemini-3.1-flash-image"


def test_generate_sends_prompt_text_as_first_content_item() -> None:
    models = _FakeModels(response=_success_response())
    provider = _provider(models)

    provider.generate(GenerationRequest(modality="image", prompt_text="a red bird"))

    assert models.calls[0]["contents"][0] == "a red bird"


def test_generate_includes_negative_prompt_when_present() -> None:
    models = _FakeModels(response=_success_response())
    provider = _provider(models)

    provider.generate(
        GenerationRequest(modality="image", prompt_text="a bird", negative_prompt_text="no cats")
    )

    contents = models.calls[0]["contents"]
    assert any("no cats" in str(item) for item in contents)


# --- error mapping -----------------------------------------------------


def _client_error(code: int, message: str = "boom") -> genai_errors.ClientError:
    return genai_errors.ClientError(code, {"message": message, "status": "ERROR"})


@pytest.mark.parametrize("code", [401, 403])
def test_generate_maps_auth_errors(code: int) -> None:
    from app.core.ai.exceptions import ProviderAuthenticationError

    provider = _provider(_FakeModels(exception=_client_error(code)))
    with pytest.raises(ProviderAuthenticationError):
        provider.generate(GenerationRequest(modality="image", prompt_text="x"))


def test_generate_maps_rate_limit_error() -> None:
    provider = _provider(_FakeModels(exception=_client_error(429)))
    with pytest.raises(ProviderRateLimitError):
        provider.generate(GenerationRequest(modality="image", prompt_text="x"))


def test_generate_maps_other_client_error_to_generic_request_error() -> None:
    provider = _provider(_FakeModels(exception=_client_error(400)))
    with pytest.raises(ProviderRequestError):
        provider.generate(GenerationRequest(modality="image", prompt_text="x"))


def test_generate_maps_server_error() -> None:
    err = genai_errors.ServerError(500, {"message": "server exploded", "status": "INTERNAL"})
    provider = _provider(_FakeModels(exception=err))
    with pytest.raises(ProviderRequestError):
        provider.generate(GenerationRequest(modality="image", prompt_text="x"))


def test_generate_maps_httpx_timeout() -> None:
    provider = _provider(_FakeModels(exception=httpx.TimeoutException("timed out")))
    with pytest.raises(ProviderTimeoutError):
        provider.generate(GenerationRequest(modality="image", prompt_text="x"))


def test_generate_maps_httpx_network_error() -> None:
    provider = _provider(_FakeModels(exception=httpx.ConnectError("no route")))
    with pytest.raises(ProviderNetworkError):
        provider.generate(GenerationRequest(modality="image", prompt_text="x"))


def test_generate_maps_prompt_level_safety_block_to_rejection() -> None:
    response = _FakeResponse(prompt_feedback=_FakePromptFeedback(block_reason="SAFETY"))
    provider = _provider(_FakeModels(response=response))
    with pytest.raises(ProviderRejectionError):
        provider.generate(GenerationRequest(modality="image", prompt_text="x"))


def test_generate_maps_non_stop_finish_reason_to_rejection() -> None:
    response = _FakeResponse(candidates=[_FakeCandidate([_FakePart()], finish_reason="SAFETY")])
    provider = _provider(_FakeModels(response=response))
    with pytest.raises(ProviderRejectionError):
        provider.generate(GenerationRequest(modality="image", prompt_text="x"))


def test_generate_maps_no_candidates_to_malformed_response() -> None:
    provider = _provider(_FakeModels(response=_FakeResponse(candidates=[])))
    with pytest.raises(ProviderMalformedResponseError):
        provider.generate(GenerationRequest(modality="image", prompt_text="x"))


def test_generate_maps_no_image_part_to_malformed_response() -> None:
    response = _FakeResponse(candidates=[_FakeCandidate([_FakePart(data=None)])])
    provider = _provider(_FakeModels(response=response))
    with pytest.raises(ProviderMalformedResponseError):
        provider.generate(GenerationRequest(modality="image", prompt_text="x"))
