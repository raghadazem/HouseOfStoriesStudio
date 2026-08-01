# Reusable Prompts

Prompt fragments that are reused across many episodes rather than
written fresh each time:

- `character_lock/` — one file per character with its current master
  prompt block + negative prompt block, kept in sync with that
  character's `character_meta.yaml`.
- `style_lock/` — the shared visual-style prompt block (art style,
  rendering look) used in every image/video prompt regardless of
  which character is in the shot.

Not yet populated — no character or style lock has been approved yet.
Episode-specific prompts live in each episode's own
`03_image_prompts.md` / `04_video_prompts.md` instead.
