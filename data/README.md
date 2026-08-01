# Runtime Data (not source code)

This directory holds machine-local runtime state: the SQLite database
(`studio.db`, created starting in Milestone 2), rotating log files
(`logs/app.log`), and any local-only config (`config.local.yaml`).

Everything in this directory except this `README.md` is git-ignored —
it's per-machine runtime state, not something to version control or
back up via Git. See `docs/07_DEVELOPMENT_PLAN.md` §25 for the actual
backup strategy for creative assets and database state.
