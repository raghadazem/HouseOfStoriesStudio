"""ThumbnailWorkflow — generates a candidate episode thumbnail image.

Lands as an ordinary draft asset (``role=None``) — promoting a
generated thumbnail to the ``"final_thumbnail"`` role that
``ProductionChecklistService``/``ExportPackageService`` key off
(``docs/16_EXPORT_PACKAGE.md``) remains an explicit human decision, per
the "no automatic promotion of a generated asset" rule
(``docs/18_AI_ARCHITECTURE_PLAN.md`` §14).
"""

from __future__ import annotations

from app.core.ai.prompt_engine import PromptEngine
from app.core.ai.workflows.base import Workflow, WorkflowContext, WorkflowResult
from app.core.db.enums import AssetType
from app.core.services.asset_import_service import AssetImportService, ImportRequest
from app.core.services.exceptions import ValidationError


class ThumbnailWorkflow(Workflow):
    name = "thumbnail"

    def __init__(
        self,
        prompt_engine: PromptEngine | None = None,
        asset_import: AssetImportService | None = None,
    ) -> None:
        self._prompts = prompt_engine or PromptEngine()
        self._assets = asset_import or AssetImportService()

    def run(self, ctx: WorkflowContext) -> WorkflowResult:
        if ctx.episode_id is None:
            raise ValidationError("ThumbnailWorkflow requires episode_id.")

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
                asset_type=AssetType.THUMBNAIL,
                episode_id=ctx.episode_id,
                source_tool=result.provider_name,
                prompt_used_id=ctx.prompt_template_id,
                notes=ctx.notes,
            ),
        )
        return WorkflowResult(asset=asset, generation_request=request, generation_result=result)
