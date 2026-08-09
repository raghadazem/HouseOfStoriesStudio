"""CharacterReferenceWorkflow — generates a candidate reference image.

Lands in the same review queue as a manually imported reference image
(an ordinary draft ``Asset``). Deliberately does **not** auto-create a
``CharacterReference`` row — promoting a generated image to canon
reference art stays an explicit human action via
``CharacterVersionService.add_character_reference()``, per the
existing "only approved assets become reference art" rule (Milestone
3, ``docs/13_CORE_SERVICES.md``).

Production-generation policy (Milestone 7): before spending a
generation call, this workflow requires the target
``CharacterVersion`` to have complete prompt-relevant fields (see
``CharacterVersionService.validate_prompt_completeness`` — the single
source of truth for this check). This is enforced identically for
every provider, including ``MockProvider`` — the rule belongs to this
workflow/domain, never to "is this a real vs. mock provider," so a
test can exercise the exact same production rule with
``MockProvider`` that real generation enforces. It is deliberately
*not* the full ``validate_character_lock`` check (which also requires
an approved reference asset to already exist) — that would be circular
for the very workflow that produces a version's first candidate
reference image.
"""

from __future__ import annotations

from app.core.ai.prompt_engine import PromptEngine
from app.core.ai.workflows.base import Workflow, WorkflowContext, WorkflowResult
from app.core.db.enums import AssetType
from app.core.services.asset_import_service import AssetImportService, ImportRequest
from app.core.services.character_version_service import CharacterVersionService
from app.core.services.exceptions import CharacterLockIncompleteError, ValidationError


class CharacterReferenceWorkflow(Workflow):
    name = "character_reference_image"

    def __init__(
        self,
        prompt_engine: PromptEngine | None = None,
        asset_import: AssetImportService | None = None,
        character_versions: CharacterVersionService | None = None,
    ) -> None:
        self._prompts = prompt_engine or PromptEngine()
        self._assets = asset_import or AssetImportService()
        self._character_versions = character_versions or CharacterVersionService()

    def run(self, ctx: WorkflowContext) -> WorkflowResult:
        if ctx.character_version_id is None:
            raise ValidationError(
                "CharacterReferenceWorkflow requires character_version_id "
                "(a reference image is always generated for one specific "
                "locked design revision, not just 'the character')."
            )

        completeness = self._character_versions.validate_prompt_completeness(
            ctx.session, ctx.character_version_id
        )
        if not completeness.is_complete:
            raise CharacterLockIncompleteError(
                f"CharacterVersion {ctx.character_version_id} cannot be used for "
                f"generation: missing {completeness.missing_fields}.",
                missing_fields=completeness.missing_fields,
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
