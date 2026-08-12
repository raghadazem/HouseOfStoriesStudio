"""GeminiProvider — real image generation via Google's Gemini API.

Uses the official ``google-genai`` Python SDK (no unofficial wrapper).
The model identifier is configuration, never a hardcoded constant
elsewhere in the app: it comes from the ``model`` constructor argument,
falling back to the ``HOS_GEMINI_IMAGE_MODEL`` environment variable,
falling back to :data:`DEFAULT_MODEL`. This is what lets the founder's
approved primary/fallback/future-tier plan (``gemini-3.1-flash-image``
/ ``gemini-2.5-flash-image`` / ``gemini-3-pro-image``) become a config
change, not a code change, when the model needs to move.

The API key is read from the ``GEMINI_API_KEY`` environment variable
(never stored in the database, source, tests, or QSettings — see
``docs/`` Milestone 7 status for the founder-approved secrets policy).
"""

from __future__ import annotations

import mimetypes
import os
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from app.core.ai.exceptions import (
    ProviderAuthenticationError,
    ProviderMalformedResponseError,
    ProviderNetworkError,
    ProviderNotConfiguredError,
    ProviderRateLimitError,
    ProviderRejectionError,
    ProviderRequestError,
    ProviderTimeoutError,
)
from app.core.ai.provider_interface import (
    AIProvider,
    GenerationRequest,
    GenerationResult,
    ProviderCapabilities,
)
from app.core.services.storage_service import StorageService

ENV_API_KEY = "GEMINI_API_KEY"
ENV_MODEL = "HOS_GEMINI_IMAGE_MODEL"
DEFAULT_MODEL = "gemini-3.1-flash-image"

_DEFAULT_EXTENSION = ".png"

# Documented on ai.google.dev/gemini-api/docs/image-generation for
# gemini-3.1-flash-image: "Up to 4 images of characters to maintain
# character consistency" — a separate quota from the model's object
# (10) and style (3) reference categories, neither of which this
# codebase sends. See docs/32_MILESTONE_8_SCENE_IMAGE_GENERATION_STATUS.md.
_CAPABILITIES = ProviderCapabilities(max_character_references=4)

# Gemini's documented output-resolution parameter (image_config.image_size).
# 1K is both the platform default and this app's default for candidate
# exploration; 2K is the only opt-in "higher quality" tier this app
# exposes (see the Images tab) — 512px/4K are intentionally never
# requested by anything in this codebase.
DEFAULT_IMAGE_SIZE = "1K"
_VALID_IMAGE_SIZES = frozenset({"512px", "1K", "2K", "4K"})

ClientFactory = Callable[[str], genai.Client]


def _default_client_factory(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)


class GeminiProvider(AIProvider):
    """Real image generation via the official ``google-genai`` SDK."""

    name = "gemini"
    supported_modalities = frozenset({"image"})
    capabilities = _CAPABILITIES

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        storage: StorageService | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        """Build a provider instance.

        All arguments are optional so ``PROVIDER_REGISTRY`` can build
        one with no arguments (reading configuration from the
        environment) while tests can inject an explicit ``api_key`` and
        a fake ``client_factory`` — never a real network call.
        """
        self._api_key = api_key if api_key is not None else os.environ.get(ENV_API_KEY)
        self._model = model if model is not None else os.environ.get(ENV_MODEL, DEFAULT_MODEL)
        self._storage = storage or StorageService()
        self._client_factory = client_factory or _default_client_factory
        self._client: genai.Client | None = None

    @property
    def model(self) -> str:
        """The configured model identifier this instance will call."""
        return self._model

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def generate(self, request: GenerationRequest) -> GenerationResult:
        if request.modality not in self.supported_modalities:
            raise ValueError(f"GeminiProvider does not support modality {request.modality!r}.")
        if not self.is_configured():
            # AIOrchestrator.run_workflow already checks is_configured()
            # before calling generate(); this is a defensive second
            # guard for any other caller that invokes the provider
            # directly (e.g. a future CLI command or a test).
            raise ProviderNotConfiguredError(
                "GeminiProvider is not configured: no API key present "
                f"(set the {ENV_API_KEY} environment variable)."
            )

        client = self._get_client()
        contents = self._build_contents(request)
        image_size = self._resolve_image_size(request)
        config = genai_types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=genai_types.ImageConfig(image_size=image_size),
        )

        try:
            response = client.models.generate_content(
                model=self._model, contents=contents, config=config
            )
        except genai_errors.ClientError as err:
            raise self._map_client_error(err) from err
        except genai_errors.ServerError as err:
            raise ProviderRequestError(f"Gemini server error ({err.code}): {err.message}") from err
        except (httpx.TimeoutException, TimeoutError) as err:
            raise ProviderTimeoutError(f"Gemini request timed out: {err}") from err
        except httpx.HTTPError as err:
            raise ProviderNetworkError(f"Network error calling Gemini: {err}") from err

        image_bytes, mime_type = self._extract_image(response)
        output_path = self._write_temp_file(image_bytes, mime_type)

        return GenerationResult(
            output_path=output_path,
            provider_name=self.name,
            raw_response_summary=f"gemini image generation via {self._model}",
        )

    def _get_client(self) -> genai.Client:
        if self._client is None:
            self._client = self._client_factory(self._api_key)  # type: ignore[arg-type]
        return self._client

    @staticmethod
    def _resolve_image_size(request: GenerationRequest) -> str:
        """Read ``image_size`` from the request's parameters, defaulting to 1K.

        The exact value used is snapshotted onto ``GenerationJob.parameters``
        by ``generation_runner`` before this method ever runs — this is
        only where the value actually gets *applied* to the real call.
        An unrecognized value falls back to the default rather than
        being sent to Gemini as-is, since ``GenerateContentConfig``
        would otherwise surface an opaque provider-side error instead of
        a clear one.
        """
        requested = request.parameters.get("image_size", DEFAULT_IMAGE_SIZE)
        return requested if requested in _VALID_IMAGE_SIZES else DEFAULT_IMAGE_SIZE

    def _build_contents(self, request: GenerationRequest) -> list[object]:
        """Build the ``contents`` list: prompt text, then reference images.

        ``reference_asset_paths`` are managed-relative paths (see
        ``GenerationRequest`` docstring) — resolved through
        ``StorageService`` the same way every other reader of managed
        files does, never assembled as a raw filesystem path.
        """
        contents: list[object] = [request.prompt_text]
        if request.negative_prompt_text:
            contents.append(f"Avoid the following: {request.negative_prompt_text}")
        for relative_path in request.reference_asset_paths:
            absolute_path = self._storage.resolve_managed_path(relative_path)
            data = absolute_path.read_bytes()
            mime_type = mimetypes.guess_type(absolute_path.name)[0] or "image/png"
            contents.append(genai_types.Part.from_bytes(data=data, mime_type=mime_type))
        return contents

    @staticmethod
    def _map_client_error(err: genai_errors.ClientError) -> ProviderRequestError:
        if err.code in (401, 403):
            return ProviderAuthenticationError(
                f"Gemini authentication failed ({err.code}): {err.message}"
            )
        if err.code == 429:
            return ProviderRateLimitError(
                f"Gemini rate limit or quota exceeded ({err.code}): {err.message}"
            )
        if err.code == 408:
            return ProviderTimeoutError(f"Gemini request timed out ({err.code}): {err.message}")
        return ProviderRequestError(f"Gemini rejected the request ({err.code}): {err.message}")

    @staticmethod
    def _extract_image(response: genai_types.GenerateContentResponse) -> tuple[bytes, str]:
        """Pull the first inline image out of a response, or raise.

        Any prompt-level block, a non-``STOP`` finish reason, or a
        response with no image part is treated as a provider rejection
        or a malformed response — never silently returns empty bytes.
        """
        feedback = response.prompt_feedback
        if feedback is not None and feedback.block_reason is not None:
            detail = f" — {feedback.block_reason_message}" if feedback.block_reason_message else ""
            raise ProviderRejectionError(
                f"Gemini declined to generate an image: {feedback.block_reason}{detail}"
            )
        if not response.candidates:
            raise ProviderMalformedResponseError("Gemini returned no candidates.")

        candidate = response.candidates[0]
        finish_reason = candidate.finish_reason
        if finish_reason is not None and finish_reason != genai_types.FinishReason.STOP:
            raise ProviderRejectionError(
                f"Gemini declined to complete the image (finish_reason={finish_reason})."
            )
        if candidate.content is None or not candidate.content.parts:
            raise ProviderMalformedResponseError("Gemini response had no content parts.")

        for part in candidate.content.parts:
            if part.inline_data is not None and part.inline_data.data:
                return part.inline_data.data, part.inline_data.mime_type or "image/png"
        raise ProviderMalformedResponseError("Gemini response contained no image data.")

    @staticmethod
    def _write_temp_file(image_bytes: bytes, mime_type: str) -> Path:
        extension = mimetypes.guess_extension(mime_type) or _DEFAULT_EXTENSION
        temp_dir = Path(tempfile.gettempdir()) / "house_of_stories_gemini_provider"
        temp_dir.mkdir(parents=True, exist_ok=True)
        output_path = temp_dir / f"gemini_{uuid.uuid4().hex}{extension}"
        output_path.write_bytes(image_bytes)
        return output_path
