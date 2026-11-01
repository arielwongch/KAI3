# Local setup and startup

Status: implemented documentation and runtime conventions. Reviewed on 2026-11-02.
Basic Windows setup and local HTTP startup verified with Python 3.12.10 on that date.

## Purpose and setup contract

The [README setup instructions](../README.md#local-setup) are the canonical command
reference. Run commands from the project root, choose the block for the operating
system and shell, and stop after a failed command. macOS/Linux commands target
Bash or Zsh; Windows commands target PowerShell.

Python 3.12 is the documented version for the local ML dependencies. On Windows,
`py -0p` lists registered interpreters and `py -3.12 --version` must report 3.12.x
before creating `venv`. A working global `python` command does not establish that
the required version or a virtual environment is selected.
The README includes a per-user WinGet installation command when the required
interpreter is missing; repeat the launcher version check after installation.

Windows installation and launch commands invoke `venv\Scripts\python.exe`
directly, so activation and execution-policy changes are unnecessary. The README
environment check must report Python 3.12.x, the environment's executable path,
and `Virtual environment: True`. macOS/Linux users create the environment with
`python3.12`, activate `venv/bin/activate`, and then use its `python` command.
The Windows environment check uses `-X utf8` so printing a non-ASCII executable
path does not fail under a legacy console encoding.

Copy `src/.env.example` to `src/.env` only on initial setup and configure the
DeepSeek key before chat or benchmark API use. The Windows setup block copies
only if `src/.env` does not exist. Manually recopying the example overwrites saved
configuration. `src/.env`, `venv/`, and `.venv/` are excluded from Git.

## Server and message behavior

The local server defaults to `127.0.0.1:5000`; `HOST` and `PORT` configure the bind
address and port. The README includes shell-specific alternate-port commands.
Stop the server with Ctrl+C. Subsequent launches reuse the environment; reinstall
requirements when they change.
After changing templates or scripts, restart the local server and reload the page
if it is still showing the previous layout. The three workspaces share
`workspace_sidebar.html`, `workspace-shell.js`, and `style.css`; Compare adds
scoped styles and behavior. Public assets are explicitly allowlisted; source,
Jinja templates, and `.env` are not served as arbitrary static files.

| Message or symptom | Meaning and response |
| --- | --- |
| `python3.12` or `source` is not recognized in PowerShell | The macOS/Linux block was used; select the Windows block and check Python 3.12 availability. |
| `py -3.12` cannot find Python | Install Python 3.12 with the Windows launcher, reopen the terminal, and repeat the version check. |
| Packages resolve under a global Python directory | Check the interpreter path and virtual-environment flag before installing or launching. |
| `Requirement already satisfied` or a pip update notice | Informational package-manager output. |
| Flask development-server warning | Expected for local development; the built-in server is not a production deployment. |
| `Skipping unreadable benchmark snapshot` | One local saved run could not load; inspect the named file and follow the recovery guidance. Other valid runs still load. |

## Runtime data and recovery boundary

Web benchmark snapshots, input files, worker logs, leases, and control files live
under `instance/benchmark_runs/`. `instance/` is excluded from Git; previously
tracked files were removed from the index with local content preserved. Exported
reports intended for sharing belong under `data/result/`.
Uploads and benchmark **Export to Compare Runs** save named JSONs in that shared
folder. Older nested uploads remain supported. The
[result-library specification](frontend/compare_runs.md#library-upload-and-save-flow)
owns duplicate choices, selected-only downloads, rename/delete, and path guards.
These exports are analysis copies and are distinct from resumable job snapshots.

The [results and resume specification](benchmark/results_and_resume.md#snapshot-validation-and-damaged-file-recovery)
owns snapshot validation, warning behavior, recovery-file exclusion, and legacy
resume restrictions. Recovery is manual: the server leaves invalid files unchanged
and does not choose between conflicting saved-result variants.

## Source and verification

[README.md](../README.md), [.gitignore](../.gitignore),
[app.py](../src/app.py), and [BenchmarkStore.py](../src/BenchmarkStore.py) define
the setup and runtime behavior. [Snapshot-restore tests](../tests/test_snapshot_restore.py)
verify file preservation and tolerant loading; they do not install Python or
validate a clean environment's ML dependency installation.

On 2026-11-02, **33 targeted offline tests passed** on the available Python
3.11.3 interpreter, with no model downloads or paid API calls. Python 3.12 was
not registered with the local launcher, and neither `venv` nor `.venv` existed
during initial diagnosis.

The same-day follow-up installed Python 3.12.10 for the current user, created a
clean isolated `venv`, and installed `requirements.txt`. `pip check` found no
broken requirements, and both snapshot-restore tests passed under Python 3.12.
A real `src/app.py` subprocess served `/`, `/chat`, `/benchmark`, and `/compare`
with HTTP 200 on a temporary loopback port, then was stopped. The HTTP check used
dummy credentials and offline model settings; no provider calls or model downloads
were made. This completes basic local setup/startup acceptance, not full-suite,
real-model, or provider-integration validation on Python 3.12.
Subsequent result/UI checks are recorded separately in
[updates](../UPDATES.md#verification-and-outstanding-work); the earlier setup-only
scope should not be read as the latest application test inventory.
