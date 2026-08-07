# Product Vision

## What HouseOfStoriesStudio Is

HouseOfStoriesStudio is **not a demo project.** It is a production-management
and consistency-enforcement application, and it exists to serve a real
commercial goal: producing House of Stories (بيت الحكايات), an original
Arabic-language children's animation brand, starting with a YouTube channel
starring two sisters, **Melissa** and **Bilsan** (`docs/00_PROJECT_OVERVIEW.md`,
`docs/01_BRAND_BIBLE.md`, `docs/02_CHARACTER_BIBLE.md`).

The application itself does not generate art, video, voice, or music — those
are produced in external tools, manually today and increasingly through
pluggable AI providers over time (see §5). What it *does* own is the
production system around that content: episodes, characters and their
canonical visual identity, prompts, imported assets, approval and licensing
status, and export packaging (`README.md`, `docs/07_DEVELOPMENT_PLAN.md`).

It is intended to become a real **AI-powered animation production studio's
operating system** — the software layer that lets a small team (today, a
solo founder) produce animated content at a consistency and speed that
would otherwise require a much larger studio.

---

## Long-Term Goals

- **Character consistency at scale.** The single highest-risk, highest-value
  problem this product solves is keeping Melissa and Bilsan visually
  consistent across dozens (eventually hundreds) of independently generated
  assets, without a trained model in the MVP and *with* one eventually
  (`docs/07_DEVELOPMENT_PLAN.md` §13, §35 Version 2 Scope).
- **A repeatable pipeline, not a one-off project.** `idea → lesson → outline
  → script → storyboard → image_prompts → video_prompts → voice → song →
  editing → thumbnail → seo → ready_to_publish → published` is meant to run
  for episode 1 exactly as it runs for episode 100 (`docs/07` §15).
- **Growing automation surface area over time**, in the priority order
  already laid out (`docs/07` §21): scaffolding → prompt composition →
  asset import → media processing → generative provider integration →
  publish-readiness gating → eventually upload automation. Each step is
  additive to the existing architecture, not a rewrite of it — see
  [ARCHITECTURE_PRINCIPLES.md](ARCHITECTURE_PRINCIPLES.md) §2.
- **A product, not just a personal tool.** Decisions should be made as if
  this system might one day run a real studio's entire production pipeline,
  onboard collaborators, or become the reference example of how a small
  team builds and ships AI-assisted animated content.

---

## Commercial Direction

- The channel is the first product; the studio tooling is the durable
  asset. Content is Arabic-first, values-driven, and educational, for
  children ages 3–7, under a brand the founder is building deliberately
  around originality (not a copy of any existing franchise) and
  monetization-eligible rights on every asset (`docs/07` §24).
- **Free/local-tool-first**, not because paid tools are off the table
  forever, but because the MVP commits to zero required recurring cost —
  the architecture (a pluggable `AIProvider` interface, tool-agnostic asset
  import) is what lets that constraint lift later without a rewrite
  (`docs/07` §5, §11).
- Licensing and provenance are tracked per-asset from day one
  (`source_tool`, license notes) specifically because commercial YouTube
  monetization depends on being able to answer, per asset, "do I actually
  hold usable rights to this" (`docs/07` §24).

---

## Target Users

- **Today:** a single technical founder, acting as both the studio's
  creative director and its own tooling's primary user.
- **Near-term:** the same founder, at higher episode volume and lower
  per-episode friction, as automation (prompt composition, asset import,
  export validation) takes over mechanical steps.
- **Longer-term (aspirational, not committed):** a small production team —
  the data model already separates *who decided* from *what was decided*
  (`CharacterVersion.decided_by`, approval records) in a way that would
  support more than one person without redesign, even though multi-user
  support is explicitly out of MVP scope (`docs/07` §33, §36).

---

## Future Roadmap

Roughly in the order the codebase itself already commits to
(`docs/07_DEVELOPMENT_PLAN.md` §33–35 for the canonical, detailed version):

1. **MVP (in progress / largely built):** core data model, episode/character/
   asset/prompt management, pipeline-stage tracking, export-spec validation,
   the desktop GUI shell and its production screens.
2. **v1:** thumbnail compositing, storyboard contact sheets, template-based
   SEO drafting, captions workflow, scheduled backups, richer import
   convenience.
3. **v2:** a locally trained/fine-tuned model for materially better
   character-consistency generation, YouTube Data API upload automation
   (with manual fallback retained), basic analytics ingestion,
   multi-language/subtitle export if the channel expands beyond Arabic.
4. **Open-ended:** whatever the studio actually needs once it is producing
   at volume — the point of the architecture in
   [ARCHITECTURE_PRINCIPLES.md](ARCHITECTURE_PRINCIPLES.md) is that this
   list can keep growing without invalidating what already exists.

---

## AI-First Philosophy

AI is treated as a first-class, architecturally central concern — not a
bolt-on feature — but with a sharp, deliberate boundary:

- **Generative media is provider-agnostic by design.** `app/core/ai/`
  defines an `AIProvider` interface and an `AIOrchestrator` that
  `app/gui/` is the *only* consumer of; the GUI never imports a provider
  SDK and never knows which vendor is in use (`docs/18_AI_ARCHITECTURE_PLAN.md`
  §1, §3–5). Today only a deterministic `MockProvider` is fully wired;
  real providers (OpenAI, Claude, Gemini, Suno, Google TTS) are structural
  stubs waiting for real integration — the architecture, not just the
  intent, is already AI-ready.
- **Generated assets are first-class assets, not a special case.** A
  generated image flows through the exact same `AssetImportService` a
  manually imported one does, with `source_tool` recording which provider
  produced it (`docs/18` §2) — this is what makes "AI-powered" additive to
  the existing consistency/approval/licensing system rather than a parallel
  one.
- **Human review is a permanent gate, not a temporary MVP limitation.**
  Even as generation automates, every generated candidate asset is
  `draft` until explicitly approved against the character's canon
  reference set (`docs/07` §13). AI accelerates production; it does not
  remove the studio's creative judgment from the loop.
- **Text-assistance and generative-media are treated differently on
  purpose.** An optional `ai_provider` text-assist hook (drafting,
  phrasing, SEO copy) defaults to a no-op manual mode and is never
  required (`docs/07` §10) — the app is always fully usable with zero AI
  configured.
- Any future AI assistant *working on this codebase* (see
  [AI_COLLABORATION_GUIDE.md](AI_COLLABORATION_GUIDE.md)) should recognize
  this boundary and preserve it: new provider integrations extend the
  existing interface; they never create a second path into the GUI.

---

## The One Standing Instruction

Whenever implementing a feature, think like the CTO of a startup building a
commercial product: consider future growth, automation, user experience,
maintainability, and production workflows — not just whether the immediate
task works. If there is a significantly better long-term design, **say so
before implementing it** (see
[AI_COLLABORATION_GUIDE.md §5](AI_COLLABORATION_GUIDE.md#5-when-to-propose-vs-when-to-just-do-it)).

**Never optimize only for speed. Optimize for product quality.** See
[QUALITY_BAR.md](QUALITY_BAR.md) for the concrete checklist this translates
into at the point a task is considered complete.
