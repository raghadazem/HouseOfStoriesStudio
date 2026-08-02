# 15 — Approval and License Workflow

**Milestone:** 3 — Core Services
**Services:** `ApprovalService` (`approval_service.py`), `LicenseService` (`license_service.py`)

---

## 1. ApprovalService: One Generic, Immutable Audit Trail

Seven entity types can be approved/rejected: `Asset`, `CharacterVersion`, `CharacterReference`, `Episode`, `Scene`, `Short`, `PromptTemplate`. Rather than building per-entity approval logic seven times, `ApprovalService` is **entity-status-agnostic**: it only ever creates and reads `ApprovalRecord` rows keyed by `(entity_type, entity_id)`.

```
ENTITY_TYPE_MODELS = {
    "asset": Asset, "character_version": CharacterVersion,
    "character_reference": CharacterReference, "episode": Episode,
    "scene": Scene, "short": Short, "prompt_template": PromptTemplate,
}
```

### Why it never touches the target entity's own status column

Some of these entities *also* have their own status-like column (`Asset.approval_status`, `CharacterVersion.status`) for domain-specific reasons; most don't (`Episode`, `Scene`, `Short`, `PromptTemplate` have no approval column at all). If `ApprovalService` tried to keep all of these in sync, it would need intimate, growing knowledge of every entity's state machine — exactly the kind of coupling a "generic" service should avoid.

Instead: **`ApprovalService.approve_entity()`/`reject_entity()`/`request_changes()` only ever write an `ApprovalRecord`.** The entity-specific service that owns a domain state machine (e.g. `CharacterVersionService.approve_character_version`) calls `ApprovalService` as one step of its own transaction, and *separately* updates its own status column, with its own domain validation (version must currently be `in_review`) applied first. This is what "approval must not bypass domain validation" means in practice: the generic approve-call alone changes nothing about domain state, so there's no path that skips the domain-specific checks.

### Immutability

`ApprovalRecord` rows are **never updated**, only inserted — `ApprovalService._record()` always does `session.add(new_record)`, never `session.query(...).update(...)`. `list_approval_history()` returns every decision ever made, in order; `get_current_approval_state()` reads the most recent one. Verified by `tests/unit/test_approval_service.py::test_approval_records_are_never_mutated_in_place`.

### Required notes

`reject_entity()` and `request_changes()` both raise `ValidationError` if `notes` is empty/whitespace — per the founder's rule that a rejection or changes-requested decision must explain why. `approve_entity()` has no such requirement (an approval is self-explanatory; notes are optional).

### `submit_for_review`

Deliberately writes nothing. "Submitted" isn't one of the three recorded decisions (`approved`/`rejected`/`needs_changes`) — it validates the entity exists and returns its current approval state as a read-only checkpoint. The actual `draft -> in_review` transition (where one exists, e.g. on `CharacterVersion`) is the entity-specific service's job.

## 2. LicenseService: History, Not a Single Mutable Record

Per the founder's explicit decision: **multiple `LicenseRecord` rows per asset are valid and expected.** They form an append-only history, not one record that gets overwritten as terms change.

- `add_license_record()` always inserts a new row.
- `update_license_record()` corrects fields on one *specific existing* record (e.g. fixing a typo in `terms_summary`) — this is not the same as adding a new decision, so mutating that one row in place is fine.
- `verify_license()` sets `verified=True`/`verified_at` on a specific record, in place — verification is a property of that record, not a new decision.
- `invalidate_license()` **never deletes**. It appends an `[INVALIDATED <timestamp>]: <reason>` marker to that record's `notes` and flips its `commercial_use_allowed` to `False`. The fact that a license was once believed valid and later invalidated is itself worth preserving.

### Commercial readiness

`calculate_asset_commercial_readiness(asset_id)` looks only at the **most recent** license record for that asset (`list_asset_license_history()[-1]`) and returns a `CommercialReadinessResult(is_ready, reason)`:

| Condition | `is_ready` |
|---|---|
| No license record exists at all | `False` — "unknown" |
| Latest record's `commercial_use_allowed` is `None` | `False` — "unknown" |
| Latest record's `commercial_use_allowed` is `False` | `False` — "forbidden" |
| `attribution_required=True` but `attribution_text` is empty | `False` — "attribution missing" |
| Otherwise | `True` |

This directly implements "an asset is not commercially ready when commercial use is unknown or forbidden" and "attribution-required assets must include attribution text."

### Attribution text and license proof

- `generate_attribution_text(asset_id)` concatenates `attribution_text` from every history record that has `attribution_required=True`, de-duplicated, in chronological order.
- `LicenseRecord.proof_relative_path` (added this milestone) holds a **managed relative path** to a proof file (a license screenshot, a receipt) — validated with the exact same `validate_relative_path` rule `Asset.relative_path` uses (`app/core/models/_path_validation.py`, shared between the two models). It is never a database blob; the actual file, if any, is imported like any other asset and only its path is referenced here.

## 3. How the Checklist Uses Both Services

`ProductionChecklistService` (`docs/13_CORE_SERVICES.md` §4) evaluates, for every asset with a `role` starting `final_` on an episode:

- **`license_requirements_satisfied`** — every final asset has at least one `LicenseRecord` at all.
- **`commercial_use_acceptable`** — every final asset's latest record has `commercial_use_allowed=True`.
- **`attribution_present`** — every final asset that requires attribution has `attribution_text` set.

These are three separate blocking checks (not folded into one), so the founder's export-time `license_report.md` (`docs/16_EXPORT_PACKAGE.md`) can say precisely which of the three is missing, per asset.
