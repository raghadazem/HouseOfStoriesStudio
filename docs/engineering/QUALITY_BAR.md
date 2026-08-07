# Quality Bar

HouseOfStoriesStudio is intended to become a **portfolio-quality commercial
application.** Every implementation should aim for production quality — not
"good enough to pass tests," but good enough that the founder (or any future
engineer) would be comfortable pointing to it as representative work.

This is the permanent completion checklist. It applies to every task, by
every contributor — human or AI — in this repository.

---

## The Checklist

Before considering **any** task complete, evaluate it against these eight
questions:

1. **Is this the simplest correct architecture?**
   Not the simplest architecture that happens to pass the tests today — the
   simplest one that correctly models the problem, per
   [ARCHITECTURE_PRINCIPLES.md](ARCHITECTURE_PRINCIPLES.md).

2. **Is this implementation maintainable in two years?**
   Will someone (including a future you) be able to read this, understand
   why it works this way, and safely change it, without archaeology?

3. **Would a senior software engineer approve this design?**
   Not "would it pass code review" in the sense of nitpicks fixed — would
   an experienced engineer look at the *design* and have no structural
   objection?

4. **Is the user experience polished?**
   For anything touching `app/gui/`: does it meet the bar in
   [UI_DESIGN_PRINCIPLES.md](UI_DESIGN_PRINCIPLES.md) — consistent tokens,
   complete interactive states, responsive behavior, real (not fabricated)
   content?

5. **Is the code easy to extend?**
   Could the next feature build on this without fighting it — extending a
   widget, adding a provider, adding a service method — rather than
   working around it?

6. **Is there unnecessary complexity?**
   Abstractions, configuration options, or indirection that exist for a
   hypothetical future need rather than the actual current one are a
   defect, not a strength — see the "no premature abstraction" guidance in
   [AI_COLLABORATION_GUIDE.md](AI_COLLABORATION_GUIDE.md).

7. **Is there unnecessary duplication?**
   Logic, widgets, or copy-pasted patterns that already exist elsewhere in
   the project and should have been reused or extended instead — see
   [ARCHITECTURE_PRINCIPLES.md](ARCHITECTURE_PRINCIPLES.md) §5–6.

8. **Is the implementation consistent with the rest of the project?**
   Same naming conventions, same service-boundary discipline, same design
   tokens, same testing patterns as everything around it — a reader should
   not be able to tell this was built in a different session, by a
   different author, or under time pressure.

---

## What to Do With a "No"

**If the answer to any question is "no," improve it before presenting the
task as complete.** This is not optional and not a suggestion to note for
later:

- Do not lower the quality bar to finish faster.
- Do not present partial or "good enough for now" work as done.
- **Optimize for long-term quality over implementation speed** — this is
  the same instruction as [PRODUCT_VISION.md](PRODUCT_VISION.md)'s closing
  line, applied concretely at the moment of declaring a task finished.

If a "no" would require changes clearly outside the current task's scope
(a deeper refactor, an unrelated fix), do not silently expand scope to fix
it either — follow the propose-first process in
[AI_COLLABORATION_GUIDE.md §5](AI_COLLABORATION_GUIDE.md#5-when-to-propose-vs-when-to-just-do-it):
name the issue, the improvement, why it's better, and the estimated impact,
then wait for a decision before touching it.

---

## Where This Fits

This checklist is the last gate before a milestone is considered done —
after the tests pass and `ruff check .` is clean (mechanical correctness),
and before the commit is made and review is requested (see
[ENGINEERING_WORKFLOW.md](ENGINEERING_WORKFLOW.md) §1). Passing tests proves
the code works; this checklist is what proves the code is *good*.
