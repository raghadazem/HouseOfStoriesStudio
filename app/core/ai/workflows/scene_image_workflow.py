"""SceneImageWorkflow — generates a candidate image for one Scene.

If ``character_version_id`` is given, that character's locked prompt
block (master prompt, palette, approved reference art) is merged into
the rendered scene prompt via ``PromptEngine`` — the mechanism that
keeps a generated scene image on-model for the character it names.
Milestone 3.5 supports locking to at most one character per scene-image
request; merging every character present in a multi-character scene is
a natural follow-on once a concrete multi-character template exists to
test it against — not built now to avoid speculative complexity.
"""

from __future__ import annotations

from app.core.ai.prompt_engine import PromptEngine
from app.core.ai.workflows.base import Workflow, WorkflowContext, WorkflowResult
from app.core.db.enums import AssetType
from app.core.services.asset_import_service import AssetImportService, ImportRequest
from app.core.services.exceptions import ValidationError


class SceneImageWorkflow(Workflow):
    name = "scene_image"

    def __init__(
        self,
        prompt_engine: PromptEngine | None = None,
        asset_import: AssetImportService | None = None,
    ) -> None:
        self._prompts = prompt_engine or PromptEngine()
        self._assets = asset_import or AssetImportService()

    def run(self, ctx: WorkflowContext) -> WorkflowResult:
        if ctx.episode_id is None or ctx.scene_id is None:
            raise ValidationError("SceneImageWorkflow requires episode_id and scene_id.")

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
                asset_type=AssetType.IMAGE,
                episode_id=ctx.episode_id,
                scene_id=ctx.scene_id,
                source_tool=result.provider_name,
                prompt_used_id=ctx.prompt_template_id,
                notes=ctx.notes,
            ),
        )
        return WorkflowResult(asset=asset, generation_request=request, generation_result=result)
