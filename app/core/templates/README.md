# Core Templates

Static scaffolding templates used by the (future) `episode_service` and
`character_service` in `app/core/services/` to generate new episode
folders and character metadata files.

These are plain Jinja2 (`.j2`) template files. **No rendering code
exists yet** — that is implemented in Milestone 3. Milestone 1 only
establishes the template content and the folder layout it will produce.

- `episode/` — one template per file in a scaffolded episode folder,
  matching the structure in `docs/07_DEVELOPMENT_PLAN.md` §16 and the
  approved episode specification (8–10 minute long episode + 3 Shorts,
  one lesson, optional original song, Simple White Arabic dialogue).
- `character/` — the character metadata template implementing the
  approved Character Lock fields (docs/07 §13, and the founder's
  Milestone-approval message).
