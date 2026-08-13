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

Output format (Milestone 9 compatibility fix, see
``docs/33_MILESTONE_9_REAL_VOICE_PRODUCTION_STATUS.md`` §Output Format):
``wav_44100`` -- this app's original WAV production master -- requires
an ElevenLabs Pro-tier-or-above subscription; a Creator-tier account's
``text_to_speech.convert()`` call is rejected with a 403
(``subscription_required`` / ``output_format_not_allowed``), confirmed
against the real API. ``DEFAULT_OUTPUT_FORMAT`` is therefore
``mp3_44100_128`` (Creator-compatible), configurable via the
``ELEVENLABS_OUTPUT_FORMAT`` environment variable using the exact same
constructor-argument -> env var -> module-default resolution as
``ENV_MODEL`` -- never a hardcoded subscription-tier assumption. The
produced file's extension always truthfully matches the requested
format (``_extension_for_output_format``) -- an MP3 is never named
``.wav``.
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
ENV_OUTPUT_FORMAT = "ELEVENLABS_OUTPUT_FORMAT"
DEFAULT_MODEL = "eleven_multilingual_v2"

# Creator-tier compatible (Milestone 9 compatibility fix -- wav_44100
# requires ElevenLabs Pro-tier-or-above and is rejected outright on a
# Creator-tier account). Configurable via ELEVENLABS_OUTPUT_FORMAT so
# nothing here hardcodes a subscription-tier assumption; set it to
# "wav_44100" to opt back into the original WAV master on a Pro-tier
# account -- see _OUTPUT_FORMAT_EXTENSIONS for every format this
# provider knows how to name honestly on disk.
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"

# The only output_format families this provider will ever write to
# disk -- an explicit allowlist (not a MIME-type guess: audio
# extension-from-MIME-type lookups are unreliable across platforms,
# unlike GeminiProvider's image case) so a produced file's extension is
# always literally true. Extending to another ElevenLabs format (e.g. a
# future Opus/PCM need) means adding one entry here, never silently
# reusing an existing extension for different bytes.
_OUTPUT_FORMAT_EXTENSIONS: dict[str, str] = {
    "wav": ".wav",
    "mp3": ".mp3",
}

_VOICE_SETTINGS_KEYS = frozenset(
    {"stability", "similarity_boost", "style", "speed", "use_speaker_boost"}
)

# The only fields ever pulled out of an ElevenLabs error response body for
# a 401/403 message -- an explicit allowlist, not a blocklist, so a
# response shape this app doesn't already know about can never leak
# anything through (never the raw body, headers, or request data; an API
# key/Authorization value has no way to appear here by construction).
# ElevenLabs' own structured error responses nest these fields under
# "detail" -- the exact {"detail": {"type", "code", "message", "status",
# "request_id"}} shape this project observed directly from a real 401
# ("missing_permissions") during Milestone 9's own smoke testing.
_SAFE_ERROR_DETAIL_KEYS = ("type", "code", "message", "status")

ClientFactory = Callable[[str], ElevenLabs]


def _default_client_factory(api_key: str) -> ElevenLabs:
    return ElevenLabs(api_key=api_key)


def _extension_for_output_format(output_format: str) -> str:
    """The real, honest file extension for one ElevenLabs ``output_format``
    value -- never guessed, never defaulted to ``.wav`` for something
    that isn't. Raises :class:`ProviderNotConfiguredError` for any
    ``output_format`` this provider doesn't already know how to name
    correctly (e.g. raw PCM, mu-law, Opus) rather than risk mislabeling
    the bytes -- this is a configuration problem to fix, not something
    to paper over with a guessed extension.
    """
    prefix = output_format.split("_", 1)[0]
    try:
        return _OUTPUT_FORMAT_EXTENSIONS[prefix]
    except KeyError:
        known = ", ".join(f"{p}_*" for p in sorted(_OUTPUT_FORMAT_EXTENSIONS))
        raise ProviderNotConfiguredError(
            f"ElevenLabsProvider does not know how to name output_format "
            f"{output_format!r} on disk; expected one of: {known}. Set "
            f"{ENV_OUTPUT_FORMAT} to a supported format."
        ) from None


def _sanitize_error_detail(body: object) -> str | None:
    """The safe, human-readable subset of an ElevenLabs error body, or
    ``None`` if it isn't the expected ``{"detail": {...}}`` shape.

    Only ever reads :data:`_SAFE_ERROR_DETAIL_KEYS` off ``body["detail"]``
    -- never the body itself, never ``err.headers``. This is what turns
    an opaque "authentication failed (403)" into an actionable message
    like "type=authentication_error, code=unauthorized, message='The API
    key you used is missing the permission ... to execute this
    operation.', status=missing_permissions" without ever risking a
    leaked credential, even if a future ElevenLabs response accidentally
    echoed one back in some other field.
    """
    detail = body.get("detail") if isinstance(body, dict) else None
    if not isinstance(detail, dict):
        return None
    safe = {key: detail[key] for key in _SAFE_ERROR_DETAIL_KEYS if key in detail}
    if not safe:
        return None
    return ", ".join(f"{key}={value}" for key, value in safe.items())


class ElevenLabsProvider(AIProvider):
    """Real voice-line generation via the official ``elevenlabs`` SDK."""

    name = "elevenlabs"
    supported_modalities = frozenset({"voice"})

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        output_format: str | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        """All arguments optional so ``PROVIDER_REGISTRY`` can build one
        with no arguments (reading configuration from the environment)
        while tests inject an explicit ``api_key`` and a fake
        ``client_factory`` — never a real network call."""
        self._api_key = api_key if api_key is not None else os.environ.get(ENV_API_KEY)
        self._model = model if model is not None else os.environ.get(ENV_MODEL, DEFAULT_MODEL)
        self._output_format = (
            output_format
            if output_format is not None
            else os.environ.get(ENV_OUTPUT_FORMAT, DEFAULT_OUTPUT_FORMAT)
        )
        self._client_factory = client_factory or _default_client_factory
        self._client: ElevenLabs | None = None

    @property
    def model(self) -> str:
        """The configured model identifier this instance will call."""
        return self._model

    @property
    def output_format(self) -> str:
        """The configured ElevenLabs output_format this instance will request."""
        return self._output_format

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
        output_format = request.parameters.get("output_format", self._output_format)

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

        output_path = self._write_temp_file(audio_bytes, output_format)
        return GenerationResult(
            output_path=output_path,
            provider_name=self.name,
            raw_response_summary=f"elevenlabs voice generation via {self._model} ({output_format})",
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
            message = f"ElevenLabs authentication failed ({err.status_code})."
            detail = _sanitize_error_detail(err.body)
            if detail:
                message += f" {detail}"
            return ProviderAuthenticationError(message)
        if err.status_code == 429:
            return ProviderRateLimitError(f"ElevenLabs rate limit or quota exceeded ({err.status_code}).")
        return ProviderRequestError(f"ElevenLabs rejected the request ({err.status_code}): {err.body}")

    @staticmethod
    def _write_temp_file(audio_bytes: bytes, output_format: str) -> Path:
        extension = _extension_for_output_format(output_format)
        temp_dir = Path(tempfile.gettempdir()) / "house_of_stories_elevenlabs_provider"
        temp_dir.mkdir(parents=True, exist_ok=True)
        output_path = temp_dir / f"elevenlabs_{uuid.uuid4().hex}{extension}"
        output_path.write_bytes(audio_bytes)
        return output_path
