# 16 — Export Package

**Milestone:** 3 — Core Services
**Service:** `ExportPackageService` (`app/core/services/export_package_service.py`)

---

## 1. What This Is (and Isn't)

`ExportPackageService` builds a structured folder of files the founder can hand to YouTube Studio for a **manual** upload. It does **not** upload anything — there is no YouTube API call anywhere in this codebase, per the founder's explicit instruction. It also never generates video/audio/thumbnails; it only organizes and copies what already exists as approved (or draft) managed assets.

## 2. Preview vs. Final Export

```python
ExportPackageService().build_export_package(session, episode_id, preview: bool)
```

- **`preview=True`** — always builds the package, regardless of checklist state, clearly marked `DRAFT PREVIEW` in `README.md` and `publishing_checklist.md`. Lets the founder see exactly what an export would look like — including placeholders for anything not ready — at any point in production.
- **`preview=False`** (final) — first runs `ProductionChecklistService.evaluate()`; if any check is **blocking** and failed, raises `ExportBlockedError` and writes nothing. Only a fully-ready episode (per `docs/13_CORE_SERVICES.md` §5's `ready_to_publish` gate — the same checklist) produces a final export.

Both modes write to a **deterministic path**: `production/episodes/<slug>/exports/preview/` or `.../exports/final/` — not a timestamped folder — so re-running an export overwrites the previous attempt rather than accumulating exports, and running it twice against unchanged episode state produces byte-identical output (verified by `tests/integration/test_export_package_service.py::test_export_structure_is_deterministic_across_runs`).

## 3. Export Directory Structure

```
production/episodes/<slug>/exports/<preview|final>/
├── final_video.<ext>              (or final_video_PLACEHOLDER.txt)
├── thumbnail.<ext>                (or thumbnail_PLACEHOLDER.txt)
├── title_ar.txt
├── title_en.txt
├── description_ar.txt
├── description_en.txt
├── hashtags.txt
├── credits.txt
├── license_report.md
├── publishing_checklist.md
├── episode_metadata.json
├── README.md
└── shorts/
    ├── short_01/
    │   ├── working_title_ar.txt
    │   ├── working_title_en.txt
    │   ├── hook.txt
    │   ├── caption.txt
    │   ├── hashtags.txt
    │   ├── source_scenes.txt
    │   ├── final_video.<ext>       (or final_video_PLACEHOLDER.txt)
    │   ├── thumbnail.<ext>         (or thumbnail_PLACEHOLDER.txt)
    │   └── metadata.json
    ├── short_02/  (same shape)
    └── short_03/  (same shape)
```

Every field maps directly to the founder's spec: `working_title_ar`/`_en`, `hook`, `source scenes` (from `Short.source_scenes`, written as `scene_<NN>: <location>` lines), `caption`, `hashtags`, final video/thumbnail or placeholder, `metadata.json`.

## 4. Placeholders

If no asset with `role="final_video"` (or `"final_thumbnail"`) exists for the episode/Short, a `*_PLACEHOLDER.txt` file is written instead, explaining what's missing. This lets a **preview** export always succeed and clearly show gaps, without ever fabricating a fake video/thumbnail file.

## 5. Never Mutates Originals

`ExportPackageService` reads via the normal SQLAlchemy session (no writes to any model) and copies files via `StorageService.prepare_export_copy` — a temp-file-then-`os.replace` copy identical in spirit to `AssetImportService`'s atomic copy, but into an export destination rather than managed storage. The original managed asset is never opened for writing. Verified by `test_export_never_mutates_managed_originals`.

## 6. Content Details

- **`episode_metadata.json`** / each Short's `metadata.json` are written with `json.dumps(..., ensure_ascii=False)`, so Arabic text appears as real UTF-8 characters in the file, not `\uXXXX` escapes — directly satisfies "support Arabic UTF-8" and "Arabic export files."
- **No absolute paths** appear anywhere in exported metadata — `episode_metadata.json` only ever contains the episode's own fields (title, lesson, runtime, hashtags, etc.), never a filesystem path.
- **`license_report.md`** is generated per final asset via `LicenseService.calculate_asset_commercial_readiness()` and `generate_attribution_text()` — see `docs/15_APPROVAL_AND_LICENSE_WORKFLOW.md` §3.
- **`publishing_checklist.md`** renders the full `ChecklistReport`: readiness percentage, every passed check, and every failed check labeled `BLOCKING` or `warning`.

## 7. CLI Access

```bash
python -m app.cli.main export-episode <slug-or-id>              # final export (blocked if not ready)
python -m app.cli.main export-episode <slug-or-id> --preview     # draft preview, always succeeds
```

See `docs/17_MILESTONE_3_STATUS.md` for the full CLI command list.
