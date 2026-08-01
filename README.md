# House of Stories Studio — بيت الحكايات

A local, Windows-first desktop application that manages the production
of House of Stories' Arabic children's YouTube episodes (starring
Melissa/ميليسا and Bilsan/بيلسان). It does **not** generate art, video,
voice, or music — those are produced manually in external tools. The
app manages episodes, characters, prompts, imported assets, approval
status, licensing, and export packaging.

See `docs/07_DEVELOPMENT_PLAN.md` for the full architecture and
rationale, and `docs/08_IMPLEMENTATION_STATUS.md` for current build
status.

## Project layout

```
app/            Python application source (core logic + GUI + CLI)
production/     Studio creative content (characters, episodes, prompts, ...)
docs/           Project documentation
tests/          Automated tests
data/           Runtime data (SQLite DB, logs) — not version-controlled
```

`app/core/` contains all business logic and must not import anything
from `app/gui/`. This keeps the domain logic usable from a future CLI
or test suite without a GUI dependency.

## Requirements

- Windows 10/11 (primary target), or Linux/macOS for development.
- **Python 3.12**.
- [ffmpeg](https://ffmpeg.org/download.html) on `PATH` (only required
  starting Milestone 3, for export/normalization features).

## Setup (Windows, PowerShell)

```powershell
# From the repository root
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Setup (macOS/Linux, bash — used for development of this repo)

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running tests

```bash
pytest
```

## Running the application

Not yet available — the GUI is built in Milestone 4. Milestone 1 only
establishes the repository foundation (config, logging, folder layout,
production templates).

## Development principles

- Prefer free/local tools; no paid API is required to run this app.
- Original personal reference photographs must never be committed to
  this repository (see the privacy rule in
  `docs/07_DEVELOPMENT_PLAN.md` §23).
- All generated filenames use English, lowercase `snake_case`.
- User-facing content may be Arabic; the UI must render RTL text
  correctly.
