"""MockProvider — the one fully-working, offline ``AIProvider``.

Makes no network call, needs no configuration, and is always
``is_configured() -> True``. Given the same request (same modality,
prompt, negative prompt, reference paths, and parameters), it always
produces byte-identical output — this is what makes workflow tests
deterministic, and it is also required by
:class:`~app.core.services.asset_import_service.AssetImportService`'s
duplicate-checksum detection: two genuinely *different* requests must
never collide on the same checksum, or the second one would be wrongly
rejected as a re-import of the first.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from app.core.ai.provider_interface import AIProvider, GenerationRequest, GenerationResult

_EXTENSION_BY_MODALITY: dict[str, str] = {
    "image": ".png",
    "video": ".mp4",
    "voice": ".wav",
    "song": ".mp3",
    "text": ".txt",
}

# A few real magic bytes per extension, purely cosmetic — nothing in
# this codebase ever opens a generated file as a real image/audio/video
# (per the project's explicit "never inspect media content" rule), so
# these do not need to be valid files, only stable and distinct.
_MAGIC_BYTES: dict[str, bytes] = {
    ".png": b"\x89PNG\r\n\x1a\n",
    ".mp4": b"\x00\x00\x00\x18ftypmp42",
    ".wav": b"RIFF\x00\x00\x00\x00WAVEfmt ",
    ".mp3": b"ID3\x03\x00\x00\x00\x00\x00\x00",
}


class MockProvider(AIProvider):
    """Deterministic, offline stand-in for a real AI provider."""

    name = "mock_provider"
    supported_modalities = frozenset({"text", "image", "video", "voice", "song"})

    def is_configured(self) -> bool:
        return True

    def generate(self, request: GenerationRequest) -> GenerationResult:
        if request.modality not in self.supported_modalities:
            raise ValueError(f"MockProvider does not support modality {request.modality!r}.")

        digest = self._digest(request)
        extension = _EXTENSION_BY_MODALITY[request.modality]
        payload = self._build_payload(request, digest)

        temp_dir = Path(tempfile.gettempdir()) / "house_of_stories_mock_provider"
        temp_dir.mkdir(parents=True, exist_ok=True)
        output_path = temp_dir / f"mock_{request.modality}_{digest}{extension}"
        output_path.write_bytes(payload)

        return GenerationResult(
            output_path=output_path,
            provider_name=self.name,
            raw_response_summary=f"mock {request.modality} generation (digest {digest[:12]})",
        )

    @staticmethod
    def _digest(request: GenerationRequest) -> str:
        """A stable sha256 over everything that should make output differ.

        Same request -> same digest -> same bytes -> same checksum
        (reproducible). Any different field -> a different digest, so
        two distinct scenes/characters/lines never collide.
        """
        hasher = hashlib.sha256()
        hasher.update(request.modality.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(request.prompt_text.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update((request.negative_prompt_text or "").encode("utf-8"))
        hasher.update(b"\0")
        for path in sorted(request.reference_asset_paths):
            hasher.update(path.encode("utf-8"))
            hasher.update(b"\0")
        for key in sorted(request.parameters):
            hasher.update(f"{key}={request.parameters[key]!r}".encode())
            hasher.update(b"\0")
        return hasher.hexdigest()

    @staticmethod
    def _build_payload(request: GenerationRequest, digest: str) -> bytes:
        extension = _EXTENSION_BY_MODALITY[request.modality]
        header = _MAGIC_BYTES.get(extension, b"")
        body = (
            "MockProvider deterministic placeholder\n"
            f"modality={request.modality}\n"
            f"digest={digest}\n"
        ).encode()
        return header + body
