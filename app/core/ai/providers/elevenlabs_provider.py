"""ElevenLabsProvider — real voice-line generation via the official ElevenLabs SDK.

Uses the official ``elevenlabs`` Python SDK (no unofficial wrapper),
mirroring ``GeminiProvider``'s exact shape (Milestone 7/8): configuration
via constructor argument -> environment variable -> module default,
credential read only from ``ELEVENLABS_API_KEY`` (never stored in the
database, source, tests, or QSettings), and provider-specific errors
mapped onto this app's existing, vendor-agnostic exception hierarchy
so nothing above this file ever parses a provider-specific string.

Designed voices only, never cloning by default: ``request.parameters``
must carry a real ``voice_id`` (an ElevenLabs Voice Library voice id,
chosen by a human when creating a ``VoiceProfile`` — see
``app.core.services.voice_profile_service``) — this provider has no
code path that uploads reference audio to create a cloned voice.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path

import httpx
from elevenlabs.client import ElevenLabs
from elevenlabs.core.api_error import ApiError
from elevenlabs.types.voice_settings import VoiceSettings

from app.core.ai.exceptions import (
    ProviderAuthenticationError,
    ProviderMalformedResponseError,
    ProviderNetworkError,
    ProviderNotConfiguredError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderTimeoutError,
)
from app.core.ai.provider_interface import AIProvider, GenerationRequest, GenerationResult

ENV_API_KEY = "ELEVENLABS_API_KEY"
ENV_MODEL = "ELEVENLABS_VOICE_MODEL"
DEFAULT_MODEL = "eleven_multilingual_v2"

# WAV production master (Milestone 9 Decision 7) -- never MP3 by
# default. Overridable via request.parameters["output_format"] only if
# a future need arises; nothing in this codebase requests anything else.
DEFAULT_OUTPUT_FORMAT = "wav_44100"

_VOICE_SETTINGS_KEYS = frozenset(
    {"stability", "similarity_boost", "style", "speed", "use_speaker_boost"}
)

ClientFactory = Callable[[str], ElevenLabs]


def _default_client_factory(api_key: str) -> ElevenLabs:
    return ElevenLabs(api_key=api_key)


class ElevenLabsProvider(AIProvider):
    """Real voice-line generation via the official ``elevenlabs`` SDK."""

    name = "elevenlabs"
    supported_modalities = frozenset({"voice"})

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        """All arguments optional so ``PROVIDER_REGISTRY`` can build one
        with no arguments (reading configuration from the environment)
        while tests inject an explicit ``api_key`` and a fake
        ``client_factory`` — never a real network call."""
        self._api_key = api_key if api_key is not None else os.environ.get(ENV_API_KEY)
        self._model = model if model is not None else os.environ.get(ENV_MODEL, DEFAULT_MODEL)
        self._client_factory = client_factory or _default_client_factory
        self._client: ElevenLabs | None = None

    @property
    def model(self) -> str:
        """The configured model identifier this instance will call."""
        return self._model

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def generate(self, request: GenerationRequest) -> GenerationResult:
        if request.modality not in self.supported_modalities:
            raise ValueError(f"ElevenLabsProvider does not support modality {request.modality!r}.")
        if not self.is_configured():
            # AIOrchestrator.run_workflow already checks is_configured()
            # before calling generate(); this is a defensive second
            # guard for any other caller that invokes the provider
            # directly (e.g. a future CLI command or a test).
            raise ProviderNotConfiguredError(
                "ElevenLabsProvider is not configured: no API key present "
                f"(set the {ENV_API_KEY} environment variable)."
            )

        voice_id = request.parameters.get("voice_id")
        if not voice_id:
            raise ProviderRequestError(
                "ElevenLabsProvider.generate() requires request.parameters['voice_id'] "
                "(the active VoiceProfile's provider_voice_id)."
            )

        client = self._get_client()
        voice_settings = self._build_voice_settings(request.parameters)
        output_format = request.parameters.get("output_format", DEFAULT_OUTPUT_FORMAT)

        try:
            chunks = client.text_to_speech.convert(
                voice_id,
                text=request.prompt_text,
                model_id=self._model,
                output_format=output_format,
                voice_settings=voice_settings,
            )
            audio_bytes = b"".join(chunks)
        except ApiError as err:
            raise self._map_api_error(err) from err
        except (httpx.TimeoutException, TimeoutError) as err:
            raise ProviderTimeoutError(f"ElevenLabs request timed out: {err}") from err
        except httpx.HTTPError as err:
            raise ProviderNetworkError(f"Network error calling ElevenLabs: {err}") from err

        if not audio_bytes:
            raise ProviderMalformedResponseError("ElevenLabs returned no audio data.")

        output_path = self._write_temp_file(audio_bytes)
        return GenerationResult(
            output_path=output_path,
            provider_name=self.name,
            raw_response_summary=f"elevenlabs voice generation via {self._model}",
        )

    def _get_client(self) -> ElevenLabs:
        if self._client is None:
            self._client = self._client_factory(self._api_key)  # type: ignore[arg-type]
        return self._client

    @staticmethod
    def _build_voice_settings(parameters: dict[str, object]) -> VoiceSettings | None:
        """Pick out the known ElevenLabs voice-tuning keys from a
        ``VoiceProfile.default_parameters``-derived ``parameters`` dict.

        Returns ``None`` (ElevenLabs' own account/voice default) rather
        than an empty ``VoiceSettings`` when nothing was configured —
        never invents stability/style numbers this app didn't decide.
        """
        found = {key: parameters[key] for key in _VOICE_SETTINGS_KEYS if key in parameters}
        return VoiceSettings(**found) if found else None

    @staticmethod
    def _map_api_error(err: ApiError) -> ProviderRequestError:
        if err.status_code in (401, 403):
            return ProviderAuthenticationError(f"ElevenLabs authentication failed ({err.status_code}).")
        if err.status_code == 429:
            return ProviderRateLimitError(f"ElevenLabs rate limit or quota exceeded ({err.status_code}).")
        return ProviderRequestError(f"ElevenLabs rejected the request ({err.status_code}): {err.body}")

    @staticmethod
    def _write_temp_file(audio_bytes: bytes) -> Path:
        temp_dir = Path(tempfile.gettempdir()) / "house_of_stories_elevenlabs_provider"
        temp_dir.mkdir(parents=True, exist_ok=True)
        output_path = temp_dir / f"elevenlabs_{uuid.uuid4().hex}.wav"
        output_path.write_bytes(audio_bytes)
        return output_path
