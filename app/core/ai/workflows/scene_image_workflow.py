"""SceneImageWorkflow — generates a candidate image for one Scene.

Milestone 8: the primary path renders directly from
``ctx.rendered_prompt_text``/``rendered_negative_prompt_text`` — the
scene's own authored, human-editable ``Scene.prompt_text``/
``negative_prompt_text`` (composed by ``PromptComposerService``,
freely hand-edited afterward), sent verbatim, with reference images for
every present character already resolved by
``ReferenceSelectionService`` into ``rendered_reference_asset_paths``.
This bypasses ``PromptEngine``/``PromptTemplate`` entirely — there is
nothing for a template renderer to do with text that's already final,
and multi-character scenes need more than the single
``character_version_id`` a template-rendered request could carry.

The legacy template-based path (``ctx.prompt_template_id`` given,
single ``character_version_id``) is kept as a fallback for
backward compatibility — Milestone 3.5's original tests still exercise
it unchanged.
"""

from __future__ import annotations

from app.core.ai.prompt_engine import PromptEngine
from app.core.ai.provider_interface import GenerationRequest
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

        if ctx.rendered_prompt_text is not None:
            request = GenerationRequest(
                modality="image",
                prompt_text=ctx.rendered_prompt_text,
                negative_prompt_text=ctx.rendered_negative_prompt_text,
                reference_asset_paths=list(ctx.rendered_reference_asset_paths),
                parameters=dict(ctx.parameters),
            )
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
                asset_type=AssetType.IMAGE,
                episode_id=ctx.episode_id,
                scene_id=ctx.scene_id,
                source_tool=result.provider_name,
                prompt_used_id=ctx.prompt_template_id,
                notes=ctx.notes,
            ),
        )
        return WorkflowResult(asset=asset, generation_request=request, generation_result=result)
