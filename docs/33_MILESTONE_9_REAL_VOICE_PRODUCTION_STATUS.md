# 33 — Milestone 9 Status: Real Voice Production

**Milestone:** 9 — real, per-character/Narrator voice-line generation for Episode 001, built on Milestone 7/8's `GenerationJob`/`AIOrchestrator`/`CandidateReviewDialogBase` architecture.
**Builds on:** `docs/18` (AI architecture), `docs/31` (Milestone 7 — character reference generation), `docs/32` (Milestone 8 — scene image generation).

---

## 1. Architecture

```
Scene.dialogue_ar (authored, human-edited, sole source of truth)
  → SceneService.sync_dialogue_lines   (stable DialogueLine identity across edits/reorder)
  → SceneService.resolve_speaker       (Character, or a NON_CHARACTER_SPEAKERS entry, or unresolved)
  → VoiceGenerationReadinessService    (can this line generate right now?)
  → run_voice_line_batch               (new sibling to run_scene_image_batch)
  → GenerationJob                      (same table, same lifecycle, zero schema change)
  → AIOrchestrator.run_workflow
  → VoiceLineWorkflow                  (direct-prompt path; legacy template path kept as fallback)
  → ElevenLabsProvider                 (real ElevenLabs SDK; output_format configurable)
  → AssetImportService
  → DRAFT voice Asset
```

`DialogueLine` gives every authored line a stable UUID across reorder/insertion/edit (`(speaker_raw, authored_text)` matched FIFO per key, consumed in order — see `tests/unit/test_dialogue_line_reconciliation.py`); an edit to a line's own words supersedes it (`is_current=False`, never deleted, never reattached). `VoiceProfile` gives each speaker (a `Character`, or a non-Character identity — the Narrator, or an episode-local supporting character like Bird/Turtle Mother) a persistent voice identity, approval-gated via the existing generic `ApprovalService` (`entity_type="voice_profile"`), at most one `is_active` per speaker.

## 2. Non-Character Speaker Resolution

`SceneService.resolve_speaker` resolves a raw `dialogue_ar` speaker string to either a `Character` (by `name_ar`/`name_en`) or a non-Character speaker via `NON_CHARACTER_SPEAKERS` (`app/core/models/voice_profile.py`) — a small, explicit `(speaker_key, display_label, aliases)` registry, matched case-insensitively, exact membership only (no fuzzy/substring matching). Originally this covered only the Narrator; Episode 001's Bird and Turtle Mother exposed the gap (their `VoiceProfile`s existed, approved and active, but their `dialogue_ar` lines — `العصفور`, `أم السلحفاة` — could never resolve, permanently blocking 3 of 44 spoken lines). The fix generalized the single hardcoded narrator-alias set into this one registry, read by both `resolve_speaker` and the Voice tab's Voice Profiles summary (`_VoiceProfilesSummary.refresh()`, `app/gui/pages/voice_workflow.py`) — the two can no longer drift apart. Adding a future non-Character speaker is one registry entry, never a new special case or a new table.

## 3. Output Format (Creator vs Pro Tier)

ElevenLabs' `wav_44100` output format — this app's original WAV production master — requires an ElevenLabs **Pro-tier-or-above** subscription. Confirmed against the real API during Episode 001's first live smoke test: a Creator-tier account's `text_to_speech.convert()` call was rejected outright with a 403, `detail.code=subscription_required`, `detail.status=output_format_not_allowed`, `detail.message="Output format 'wav_44100' is only available on the Pro tier and above."` — named explicitly by ElevenLabs itself, not inferred.

**Decision: the application must not require a Pro subscription just because Milestone 9 originally chose WAV.** `ElevenLabsProvider.DEFAULT_OUTPUT_FORMAT` is now `mp3_44100_128` — supported on the Creator tier without any upgrade — and nothing in this codebase hardcodes a subscription-tier assumption:

```python
ENV_OUTPUT_FORMAT = "ELEVENLABS_OUTPUT_FORMAT"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
```

Resolved with the exact same constructor-argument → environment-variable → module-default precedence already established for `ENV_MODEL`/`ENV_API_KEY` (mirroring `GeminiProvider`'s `HOS_GEMINI_IMAGE_MODEL` philosophy). A Pro-tier account can opt back into the original WAV master at any time by setting `ELEVENLABS_OUTPUT_FORMAT=wav_44100` — no code change required. 192 kbps was considered and rejected as the default: nothing in Episode 001's production requirements justifies the extra cost/bandwidth over 128 kbps for spoken dialogue, and Creator-tier compatibility, not audio-quality ceiling, was the actual constraint being solved.

**File-format/provenance honesty.** The produced file's extension always truthfully matches the requested format — `ElevenLabsProvider._extension_for_output_format` is an explicit `{"wav": ".wav", "mp3": ".mp3"}` allowlist (not a MIME-type guess, unlike `GeminiProvider`'s image case: audio extension-from-MIME lookups are unreliable across platforms), and refuses (`ProviderNotConfiguredError`) rather than mislabel any `output_format` it doesn't already know how to name correctly. An MP3 is never named `.wav`. Every `GenerationJob.parameters["output_format"]` snapshots the exact value actually requested — a `VoiceProfile.default_parameters["output_format"]` override, if ever set, wins over the provider's own default; whichever value is chosen is both what's sent to ElevenLabs and what's snapshotted, so the two can never disagree.

**Duration measurement.** `VoiceLineWorkflow._measure_duration_seconds` dispatches on the produced file's own (always-truthful) extension: `.wav` via Python's built-in `wave` module (frame count / frame rate, unchanged from the original implementation), `.mp3` via `tinytag` (new dependency — MIT license, pure Python, zero transitive dependencies, correctly handles VBR via Xing/VBRI headers rather than a naive filesize/bitrate division). `mutagen` was considered and rejected: GPL-2.0-or-later, incompatible with this project's Proprietary license. A hand-rolled MPEG frame parser was also considered and rejected — avoiding one dependency isn't worth owning MPEG version/layer/bitrate tables and Xing/ID3 edge cases in application code when a small, correct, permissively-licensed library already solves it. Duration is never invented and never estimated from text length: any file this process can't parse yields `None`, exactly like the pre-existing WAV path already did, never a guessed number.

**Future options, not built now:** Pro-tier WAV generation (already available today via `ELEVENLABS_OUTPUT_FORMAT=wav_44100` on a Pro account — no further work needed), a later mastering/export step that transcodes MP3 masters to WAV/lossless for final delivery, or a higher ElevenLabs output tier if a concrete production-quality need arises. None of these are required for reliable Episode 001 voice production on the current subscription, which was the actual goal.

## 4. GUI

`AudioCandidateTile` (`app/gui/widgets/candidate_review.py`) was already fully format-agnostic — it resolves `Asset.relative_path` to a real path and hands it to `QMediaPlayer.setSource(QUrl.fromLocalFile(...))`, no WAV-specific assumption anywhere. No visual redesign was needed; `test_audio_candidate_tile_plays_mp3_asset` (`tests/gui/test_voice_workflow.py`) verifies the tile correctly wires a real `.mp3` `Asset` to `QMediaPlayer` the same way it already did for `.wav`.

The Voice tab's Voice Profiles summary (`_VoiceProfilesSummary`) previously hardcoded its non-Character row to the Narrator only; it now iterates `NON_CHARACTER_SPEAKERS` (§2), so Bird and Turtle Mother appear with their own approved/active status exactly like every other speaker — no unrelated GUI-only hardcoded rows.

## 5. Readiness

`VoiceGenerationReadinessService.evaluate(session, dialogue_line_id, *, provider_name, orchestrator)` — mirrors `SceneGenerationReadinessService`'s shape. Per line: speaker resolved (naming the raw string if not); an active `VoiceProfile` exists for that speaker; it's approved; the provider is configured; no `GenerationJob` already `PENDING`/`RUNNING`/`CANCEL_REQUESTED` for this exact line. A line inside an `is_song_scene` scene is never subject to these checks at all (`not_applicable_reason` set instead) — it can never surface as a Voice blocker, and is never counted as blocked.

## 6. Text Normalization & Pronunciation

`app.core.ai.text_normalization.normalize_arabic_line` applies the currently-configured global `PronunciationOverride` rows to `DialogueLine.authored_text` before sending to the provider — `authored_text` itself is never modified. Both the untouched authored text and the exact normalized text sent are snapshotted onto every `GenerationJob.parameters` (`authored_text`, `normalized_text_sent`), inspectable independently.

## 7. Episode 001 Verification

Real production content (`app.core.db.episode_001_production.populate_episode_001_production_content`): 15 scenes, 47 `DialogueLine`s, 3 in Scene 9 (the song scene, correctly excluded/NOT APPLICABLE), 44 spoken/TTS-eligible. With all six Episode 001 `VoiceProfile`s (Melissa, Bilsan, Tortor, Narrator, Bird, Turtle Mother) created, approved, and active: **44/44 READY, 0 BLOCKED** — verified against both the service layer and the real `VoiceWorkspacePanel` GUI widget instantiated against real production data.

One real, paid ElevenLabs smoke-test attempt for Melissa (voice_id `XTa3iQyMA6f1qrI4F6kZ`) is what surfaced the Creator/Pro output-format restriction described in §3 — the fix in this document is a direct result of that real-call finding, not a hypothetical.

## 8. Testing Strategy

All offline (`MockProvider`, or a fake ElevenLabs HTTP client/SDK response), except the one manual real-API smoke test noted in §7. New/extended for the output-format compatibility fix specifically:

- `tests/unit/test_elevenlabs_provider.py` — default is Creator-compatible MP3; explicit WAV request still works; `ELEVENLABS_OUTPUT_FORMAT` env var override; constructor-argument override (wins over env); unsupported `output_format` refused outright (never mislabeled).
- `tests/unit/test_ai_workflows.py` — `.mp3` duration measured correctly via `tinytag` against a real (hand-built, structurally valid) MPEG frame fixture; unrecognized extension yields `None`, never invented.
- `tests/unit/test_generation_runner_voice.py` — `output_format` provenance snapshot reflects the provider's effective default; a `VoiceProfile`-level override wins over it; full pipeline (fake `ElevenLabsProvider` HTTP client, real MP3 bytes) produces a DRAFT `.mp3` `Asset` with a correctly measured duration.
- `tests/gui/test_voice_workflow.py` — the Voice Profiles summary includes Bird/Turtle Mother with correct approved/active status (non-Character speaker resolution fix); `AudioCandidateTile` plays a real `.mp3` `Asset`.

## 9. Migration / Backward Compatibility

**No schema migration for the output-format fix.** `output_format` lives in the existing generic `GenerationJob.parameters` JSON column, exactly like `voice_id`/`candidate_index`/`normalized_text_sent` already do. `alembic check` confirms no drift. Existing WAV-produced assets and `MockProvider`'s own always-`.wav` voice output (used by every non-ElevenLabs-specific test) are completely unaffected — `MockProvider` doesn't read `ELEVENLABS_OUTPUT_FORMAT` and never did.

## 10. Known Limitations

- The `_OUTPUT_FORMAT_EXTENSIONS` allowlist only knows `wav`/`mp3` — the two families this application actually requests. A future need for raw PCM/µ-law/Opus would need one more allowlist entry, not a redesign.
- `tinytag`'s duration reading assumes a well-formed MPEG stream; a genuinely corrupt file yields `None` (never invented), same discipline as the pre-existing WAV path.
- No mastering/transcode step exists yet to convert an MP3 master to WAV for final delivery — deliberately out of scope until an actual delivery requirement calls for it (§3).
