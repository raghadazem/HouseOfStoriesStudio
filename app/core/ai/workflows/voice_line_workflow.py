"""VoiceLineWorkflow — generates a candidate audio clip for one DialogueLine.

Milestone 9: the primary path renders directly from
``ctx.rendered_prompt_text`` — the exact normalized text
``run_voice_line_batch`` computed from a stable
:class:`~app.core.models.dialogue_line.DialogueLine`'s ``authored_text``
(pronunciation overrides applied, authored text itself untouched) —
sent verbatim, bypassing ``PromptEngine``/``PromptTemplate`` entirely,
exactly mirroring ``SceneImageWorkflow``'s Milestone 8 direct-prompt
path. After a successful ``provider.generate()`` call, the resulting
file's *real* duration is measured (never invented, never trusted
verbatim from the provider — see ``docs/33_MILESTONE_9_REAL_VOICE_PRODUCTION_STATUS.md``),
dispatched on the produced file's own (always-truthful, see
``ElevenLabsProvider._extension_for_output_format``) extension: ``.wav``
via Python's built-in ``wave`` module (this app's original WAV
production master), ``.mp3`` via ``tinytag`` (Milestone 9 Creator-tier
compatibility fix -- ``wav_44100`` requires an ElevenLabs Pro-tier
subscription; ``mp3_44100_128`` is this app's current default).

The legacy template-based path (``ctx.prompt_template_id`` given) is
kept as a fallback for backward compatibility — Milestone 3.5's
original tests still exercise it unchanged; it never measures duration
(nothing produced through it was ever a real audio file).
"""

from __future__ import annotations

import wave
from pathlib import Path

from tinytag import TinyTag, TinyTagException

from app.core.ai.prompt_engine import PromptEngine
from app.core.ai.provider_interface import GenerationRequest
from app.core.ai.workflows.base import Workflow, WorkflowContext, WorkflowResult
from app.core.db.enums import AssetType
from app.core.services.asset_import_service import AssetImportService, ImportRequest
from app.core.services.exceptions import ValidationError


class VoiceLineWorkflow(Workflow):
    name = "voice_line"

    def __init__(
        self,
        prompt_engine: PromptEngine | None = None,
        asset_import: AssetImportService | None = None,
    ) -> None:
        self._prompts = prompt_engine or PromptEngine()
        self._assets = asset_import or AssetImportService()

    def run(self, ctx: WorkflowContext) -> WorkflowResult:
        if ctx.episode_id is None:
            raise ValidationError("VoiceLineWorkflow requires episode_id.")

        duration_seconds: float | None = None
        if ctx.rendered_prompt_text is not None:
            request = GenerationRequest(
                modality="voice",
                prompt_text=ctx.rendered_prompt_text,
                parameters=dict(ctx.parameters),
            )
            result = ctx.provider.generate(request)
            ctx.last_generation_result = result
            duration_seconds = self._measure_duration_seconds(result.output_path)
        else:
            request = self._prompts.build_request(
                ctx.session,
                prompt_template_id=ctx.prompt_template_id,
                variables=ctx.variables,
                character_version_id=ctx.character_version_id,
                parameters=ctx.parameters,
            )
            result = ctx.provider.generate(request)
            ctx.last_generation_result = result

        asset = self._assets.import_asset(
            ctx.session,
            ImportRequest(
                source_path=result.output_path,
                asset_type=AssetType.VOICE,
                episode_id=ctx.episode_id,
                character_version_id=ctx.character_version_id,
                dialogue_line_id=ctx.dialogue_line_id,
                duration_seconds=duration_seconds,
                source_tool=result.provider_name,
                prompt_used_id=ctx.prompt_template_id,
                notes=ctx.notes,
            ),
        )
        return WorkflowResult(asset=asset, generation_request=request, generation_result=result)

    @staticmethod
    def _measure_duration_seconds(path: Path) -> float | None:
        """Real duration, measured from the actual file's own structure.

        Never a provider-reported figure taken on faith (same discipline
        as ``GenerationJobService.mark_succeeded``'s ``cost_usd``: only
        ever an authoritative measurement, or ``None``) and never
        estimated from text length. Dispatches on the file's own
        extension -- always truthful, see
        ``ElevenLabsProvider._extension_for_output_format`` -- rather
        than on any assumption about which provider/format produced it:

        - ``.wav``: Python's built-in ``wave`` module (frame count /
          frame rate), this app's original format.
        - ``.mp3``: ``tinytag`` (correctly handles VBR via Xing/VBRI
          headers, not just a naive bitrate/filesize division), this
          app's Creator-tier-compatible default.

        ``None`` (not an exception) for any other extension or any file
        this process can't parse -- duration is a nice-to-have on
        ``Asset``, never a reason to fail an otherwise-successful
        generation.
        """
        suffix = Path(path).suffix.lower()
        if suffix == ".wav":
            try:
                with wave.open(str(path), "rb") as wav_file:
                    frames = wav_file.getnframes()
                    rate = wav_file.getframerate()
                    if rate <= 0:
                        return None
                    return frames / rate
            except (wave.Error, OSError):
                return None
        if suffix == ".mp3":
            try:
                tag = TinyTag.get(str(path), tags=False, image=False)
                return tag.duration
            except (TinyTagException, OSError):
                return None
        return None
