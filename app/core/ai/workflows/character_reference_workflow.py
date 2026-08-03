"""CharacterReferenceWorkflow — generates a candidate reference image.

Lands in the same review queue as a manually imported reference image
(an ordinary draft ``Asset``). Deliberately does **not** auto-create a
``CharacterReference`` row — promoting a generated image to canon
reference art stays an explicit human action via
``CharacterVersionService.add_character_reference()``, per the
existing "only approved assets become reference art" rule (Milestone
3, ``docs/13_CORE_SERVICES.md``).
"""

from __future__ import annotations

from app.core.ai.prompt_engine import PromptEngine
from app.core.ai.workflows.base import Workflow, WorkflowContext, WorkflowResult
from app.core.db.enums import AssetType
from app.core.services.asset_import_service import AssetImportService, ImportRequest
from app.core.services.exceptions import ValidationError


class CharacterReferenceWorkflow(Workflow):
    name = "character_reference_image"

    def __init__(
        self,
        prompt_engine: PromptEngine | None = None,
        asset_import: AssetImportService | None = None,
    ) -> None:
        self._prompts = prompt_engine or PromptEngine()
        self._assets = asset_import or AssetImportService()

    def run(self, ctx: WorkflowContext) -> WorkflowResult:
        if ctx.character_version_id is None:
            raise ValidationError(
                "CharacterReferenceWorkflow requires character_version_id "
                "(a reference image is always generated for one specific "
                "locked design revision, not just 'the character')."
            )

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
                character_version_id=ctx.character_version_id,
                source_tool=result.provider_name,
                prompt_used_id=ctx.prompt_template_id,
                notes=ctx.notes,
            ),
        )
        return WorkflowResult(asset=asset, generation_request=request, generation_result=result)
