# Windows Development

HouseOfStoriesStudio's primary target platform is Windows 10/11
(`README.md`). This document is the practical guide to setting up and
working in a correct, deterministic local Windows dev environment, and a
record of the Windows-specific issues found and fixed while doing so (see
`docs/27_WINDOWS_TEST_STABILIZATION_STATUS.md` for the full milestone
writeup this document was produced alongside).

---

## Supported Python Version

**Python 3.12** (`pyproject.toml`: `requires-python = ">=3.12"`). Verified
against **3.12.10** during this milestone — the newest 3.12.x release that
still ships an official Windows installer (3.12.11+ moved to source-only
security releases with no binary installer).

### Install Python 3.12 (recommended method)

Use the **official python.org installer**, not the Microsoft Store package.

1. Download the latest 3.12.x Windows installer from
   `https://www.python.org/downloads/release/` (the amd64 `.exe`). If the
   very latest 3.12.x patch has no Windows installer listed (it may be
   source-only), use the newest one that does.
2. Install user-scoped, with the launcher and PATH enabled:
   ```
   python-3.12.x-amd64.exe /passive InstallAllUsers=0 PrependPath=1 Include_launcher=1
   ```
3. Verify:
   ```powershell
   py --list
   py -3.12 --version
   ```

### Why not the Microsoft Store Python package

- It's a sandboxed app-execution-alias build: some file-association and
  `PATH`-precedence behavior differs from a normal interpreter, which is
  exactly the kind of ambiguity that made a stray `python` on `PATH`
  resolve to the wrong interpreter during this milestone's environment
  audit.
- It does not register itself with the `py` launcher's version registry
  the same way the official installer does, making `py -3.12` unreliable.
- It offers no practical benefit over the official installer for a
  project that already pins an exact minimum version in `pyproject.toml`.

Python 3.11 (if already present via the Store) does not need to be
uninstalled — this project simply won't run under it (see "Local `.venv`
Setup" below for why the version matters beyond the version pin itself).

---

## Local `.venv` Setup

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,gui]"
```

Verify the active interpreter actually resolved to the project's `.venv`
before doing anything else:

```powershell
python --version   # must report 3.12.x
where.exe python    # first match must be .venv\Scripts\python.exe
```

`.venv/` is git-ignored — this is your normal, permanent local dev
environment, not a throwaway.

**A PowerShell-specific gotcha worth knowing:** activating a venv (or
installing Python, or anything else that changes `PATH`/environment
variables) only affects *new* processes launched **after** the change,
read from that point's environment snapshot. A shell/terminal session
already open when you installed Python 3.12 will not see it on `PATH`
until you open a new terminal (or manually refresh `$env:Path` from the
registry) — `where.exe python` returning the old interpreter after an
install you just ran almost always means this, not a broken install.

---

## VS Code Interpreter Selection

This repo ships `.vscode/settings.json` as **git-ignored, local-only**
(the project's `.gitignore` already excludes `.vscode/`, and that's a
deliberate choice — see `docs/27_WINDOWS_TEST_STABILIZATION_STATUS.md` —
not an oversight to "fix"). Create it locally, once, per machine:

```json
{
    "python.defaultInterpreterPath": "${workspaceFolder}/.venv/Scripts/python.exe",
    "python.terminal.activateEnvironment": true
}
```

If VS Code's Python extension still shows the wrong interpreter after
this, use the **Python: Select Interpreter** command and pick
`.venv\Scripts\python.exe` explicitly — the extension caches its
interpreter list per-workspace and doesn't always pick up a `.venv`
created after the workspace was first opened.

---

## UTF-8 CLI Behavior

`app/cli/main.py` reconfigures `sys.stdout`/`sys.stderr` to UTF-8 at
startup (`_ensure_utf8_stdio`), unconditionally, on every platform. You
should never need to set `PYTHONUTF8`, `PYTHONIOENCODING`, or run
`chcp 65001` to get correct Arabic output from `hos-cli` — if you ever do
see a `UnicodeEncodeError` from a CLI command, that's a bug, not a missing
environment variable (see `docs/27` for the one this milestone found and
fixed in `show-episode`).

**If you're writing a new test that captures CLI subprocess output**
(`subprocess.run([..., "-m", "app.cli.main", ...], capture_output=True,
text=True)`), pass `encoding="utf-8"` explicitly rather than relying on
`text=True`'s locale-default decoding. The child process always emits
UTF-8 now, but Python's *parent-side* decoding under `text=True` still
defaults to the host's system locale codepage — on an English-locale
Windows machine that's usually UTF-8-compatible enough not to matter, but
it is a real, silent trap on a non-English-locale Windows install (this
was caught on a machine defaulting to `cp1255`). `tests/integration/test_cli.py::_run`
already does this correctly — copy that pattern, don't reinvent it.

---

## Windows-Specific Troubleshooting

### `FileNotFoundError` / `WinError 3` from a hardcoded `/tmp/...` path

A POSIX-style absolute path (`Path("/tmp/whatever")`) silently resolves on
Windows to a path off the *current drive's root* (`\tmp\whatever`), not a
real temp directory — it doesn't error at construction time, only later
when something tries to actually read/write it. Always use
`tempfile.gettempdir()` (see `app/core/ai/providers/mock_provider.py` for
the correct pattern) instead of a hardcoded path, in both production code
and tests.

### A test passes alone but fails in the full suite

Two confirmed causes of this in `tests/gui/`, found during this milestone
(see `docs/27` for full detail — **neither is fixed by this milestone**,
both are flagged as known, open issues):

- **Shared `QApplication` state leaking across tests.** GUI tests share
  one session-scoped `QApplication` (`qapp` fixture); a stylesheet or
  other global state applied by one test and never reset can silently
  change a later test's widget sizing/behavior. If a widget's measured
  size in a test doesn't match what you'd expect from its code alone,
  suspect this before suspecting the widget.
- **A pre-existing, unrelated bug that a fix elsewhere merely stopped
  masking.** `test_run_ai_workflow_thumbnail_and_review_queue` used to
  fail immediately at an earlier `UnicodeEncodeError` and never reached
  the code that actually has the bug (`AssetImportService.copy_file_atomic`
  intermittently raising `WinError 3` on a fresh temp file under rapid
  successive subprocess launches) — fixing the encoding issue revealed
  this, it didn't cause it. When a fix changes a test's failure message
  instead of making it pass, re-diagnose from scratch rather than
  assuming the new failure is caused by your change.

### `SAWarning: Cannot correctly sort tables; there are unresolvable cycles...`

A pre-existing warning from `alembic/env.py`'s `alembic check`/autogenerate
path, caused by mutually dependent foreign keys between `assets`,
`character_versions`, `characters`, and `shorts`. **Not addressed by this
milestone** — it's a warning, not a failure, and predates this milestone's
scope. Mentioned here only so it isn't mistaken for something this
document's fixes should have cleared.

---

## See Also

- `docs/engineering/ENGINEERING_WORKFLOW.md` — the testing/verification
  steps this document supports.
- `docs/27_WINDOWS_TEST_STABILIZATION_STATUS.md` — the milestone that
  produced this document: full root-cause writeups, the migration that
  added `ApprovalRecord.revision`, and the two open issues noted above.
