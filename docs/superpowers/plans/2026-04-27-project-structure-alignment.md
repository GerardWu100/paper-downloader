# Project Structure Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize `paper-downloader` so source code, working data, generated outputs, tests, and developer guides follow the structure requested in `AGENTS.md`.

**Architecture:** Keep the existing command-line behavior unchanged while moving implementation code into a `src/` layout and separating reusable working data from generated outputs. The pipeline remains `ISSN -> DOI queue -> metadata CSV -> PDF downloads`, but the folders make that flow explicit.

**Tech Stack:** Python 3.11+, `uv`, setuptools, pytest, ruff, TOML configuration, Markdown developer guides.

---

## File Structure

Create or modify these files and folders:

- Create: `src/`
- Move: `paper_downloader/` -> `src/paper_downloader/`
- Create: `src/GUIDE_src.md`
- Create: `src/paper_downloader/GUIDE_paper_downloader.md`
- Create: `tests/GUIDE_tests.md`
- Create: `data/GUIDE_data.md`
- Create: `data/interim/doi_queues/`
- Create: `outputs/GUIDE_outputs.md`
- Create: `outputs/metadata/`
- Create: `outputs/pdfs/`
- Create: `outputs/runs/`
- Create: `docs/GUIDE_docs.md`
- Create: `docs/reference/structure.md`
- Modify: `pyproject.toml`
- Modify: `config.toml`
- Modify: `README.md`
- Modify: `GUIDE_ROOT.md`
- Modify: `GUIDE_OVERVIEW.md`
- Modify tests only if import paths or path expectations fail after the move.

Do not edit `mynotes.md`.

---

### Task 1: Preserve Existing Work Before Restructure

**Files:**
- Read: all currently modified files from `git status --short`
- Modify: none

- [ ] **Step 1: Inspect the dirty working tree**

Run:

```bash
git status --short
```

Expected: the command prints the current modified files. At the time this plan was written, the dirty files were:

```text
 M GUIDE_ROOT.md
 M paper_downloader/cli.py
 M paper_downloader/downloader.py
 M paper_downloader/naming.py
 M tests/test_cli.py
 M tests/test_downloader.py
 M tests/test_naming.py
?? docs/superpowers/plans/2026-04-27-project-structure-alignment.md
```

- [ ] **Step 2: Review existing changes without reverting them**

Run:

```bash
git diff -- GUIDE_ROOT.md paper_downloader/cli.py paper_downloader/downloader.py paper_downloader/naming.py tests/test_cli.py tests/test_downloader.py tests/test_naming.py
```

Expected: a readable diff. Treat these edits as user-owned or previous-session-owned work. Do not discard them.

- [ ] **Step 3: Verify the pre-restructure test baseline**

Run:

```bash
uv run pytest
```

Expected: either all tests pass, or any failures are recorded as pre-existing. If tests fail before the restructure, save the failure summary in the implementation notes before continuing.

---

### Task 2: Move The Package Into `src/`

**Files:**
- Move: `paper_downloader/` -> `src/paper_downloader/`
- Modify: `pyproject.toml`

- [ ] **Step 1: Create the `src/` directory**

Run:

```bash
mkdir -p src
```

Expected: `src/` exists.

- [ ] **Step 2: Move the Python package with git tracking**

Run:

```bash
git mv paper_downloader src/paper_downloader
```

Expected: `git status --short` shows files renamed from `paper_downloader/...` to `src/paper_downloader/...`.

- [ ] **Step 3: Update packaging configuration**

Edit `pyproject.toml` so the relevant sections read exactly:

```toml
[project.scripts]
paper-downloader = "paper_downloader.cli:main"
paper-issn-to-doi = "paper_downloader.cli:fetch_dois_entrypoint"
paper-download = "paper_downloader.cli:download_entrypoint"
paper-export-metadata = "paper_downloader.cli:export_metadata_entrypoint"

[dependency-groups]
dev = [
    "pytest>=9.0.2",
    "ruff>=0.13.0",
]

[tool.pytest.ini_options]
pythonpath = ["src"]

[tool.setuptools]
package-dir = {"" = "src"}
packages = ["paper_downloader"]
```

The key change is `package-dir = {"" = "src"}`. It tells setuptools that importable packages live under `src/`.

- [ ] **Step 4: Run import and console-entrypoint smoke checks**

Run:

```bash
uv run python -c "import paper_downloader; print(paper_downloader.__name__)"
uv run paper-downloader --help
uv run paper-issn-to-doi --help
uv run paper-export-metadata --help
uv run paper-download --help
```

Expected: the import command prints `paper_downloader`, and each command prints help text without an import error.

---

### Task 3: Separate DOI Queues, Metadata, PDFs, And Run Outputs

**Files:**
- Create: `data/interim/doi_queues/`
- Create: `outputs/metadata/`
- Create: `outputs/pdfs/`
- Create: `outputs/runs/`
- Modify: `config.toml`
- Move tracked DOI queue and ledger files if they are intentionally kept as sample data.

- [ ] **Step 1: Create the new data and output directories**

Run:

```bash
mkdir -p data/interim/doi_queues outputs/metadata outputs/pdfs outputs/runs
```

Expected: all four directories exist.

- [ ] **Step 2: Move existing DOI queue and ledger examples**

Run:

```bash
git mv dois/*.txt data/interim/doi_queues/
```

Expected: DOI queue, success-ledger, and error-ledger text files move into `data/interim/doi_queues/`.

- [ ] **Step 3: Move existing metadata CSV examples**

Run:

```bash
git mv dois/*_metadata.csv outputs/metadata/
```

Expected: metadata CSV files move into `outputs/metadata/`.

- [ ] **Step 4: Remove the old DOI directory if empty**

Run:

```bash
rmdir dois
```

Expected: `dois/` is removed if empty. If it is not empty, inspect the remaining files before deciding where they belong.

- [ ] **Step 5: Update configured default paths**

Edit `config.toml` so the path section reads exactly:

```toml
# Directory for generated DOI queue files and adjacent success/error ledgers.
dois_dir = "data/interim/doi_queues"

# Directory for exported metadata CSV files.
metadata_dir = "outputs/metadata"

# Directory for downloaded PDFs.
pdfs_dir = "outputs/pdfs"
```

- [ ] **Step 6: Update any example `doi_file` comments**

In `config.toml`, replace examples that point at `dois/...` with:

```toml
# Example:
# doi_file = "data/interim/doi_queues/1467-9965_dois.txt"
```

and:

```toml
# Example:
# doi_files = [
#   "data/interim/doi_queues/1467-9965_dois.txt",
#   "data/interim/doi_queues/2214-6369_dois.txt",
# ]
```

---

### Task 4: Add Folder Guide Files

**Files:**
- Create: `src/GUIDE_src.md`
- Create: `src/paper_downloader/GUIDE_paper_downloader.md`
- Create: `tests/GUIDE_tests.md`
- Create: `data/GUIDE_data.md`
- Create: `outputs/GUIDE_outputs.md`
- Create: `docs/GUIDE_docs.md`

- [ ] **Step 1: Create `src/GUIDE_src.md`**

Write:

```markdown
# GUIDE_src

## Purpose

`src/` contains importable Python implementation code.

The project uses a `src` layout so tests and command-line entrypoints import
the installed package path instead of accidentally importing files from the
repository root.

## Contents

- `paper_downloader/`: the command-line package for DOI discovery, metadata
  export, PDF downloading, browser transport, queue progress, and filename
  naming.

## Rules

- Keep implementation code under `src/paper_downloader/`.
- Do not put generated DOI queues, metadata CSV files, PDFs, logs, notebooks,
  or manual notes here.
- Add a subfolder guide when a new meaningful implementation subfolder is
  created.
```

- [ ] **Step 2: Create `src/paper_downloader/GUIDE_paper_downloader.md`**

Write:

```markdown
# GUIDE_paper_downloader

## Purpose

`src/paper_downloader/` contains the Python package behind the command-line
tools.

The package implements this pipeline:

```text
ISSN -> DOI queue -> metadata CSV -> PDF downloads
```

`ISSN` means International Standard Serial Number. `DOI` means Digital Object
Identifier.

## Main Modules

- `cli.py`: command-line parsing, config loading, and top-level orchestration.
- `doi_sources.py`: OpenAlex and Crossref DOI discovery for one journal ISSN.
- `metadata_export.py`: Crossref and OpenAlex metadata export to CSV.
- `downloader.py`: DOI-to-PDF download flow, PDF validation, retries, and save
  behavior.
- `browser.py`: Playwright browser transport setup.
- `_http.py`: shared HTTP helpers.
- `naming.py`: title, year, and DOI-marker filename logic.
- `progress.py`: DOI queue and success/error ledger handling.

## Boundaries

- This package should not contain generated DOI files, metadata CSV files, PDFs,
  or run logs.
- Configuration defaults live in the root `config.toml`.
- User-facing usage docs live in `README.md` and `docs/user/`.
- Developer reference docs live in `docs/reference/`.
```

- [ ] **Step 3: Create `tests/GUIDE_tests.md`**

Write:

```markdown
# GUIDE_tests

## Purpose

`tests/` contains pytest coverage for the `paper_downloader` package.

## Test Organization

The current test suite is small, so tests may remain flat when that is clearer.
Use subfolders only when they improve navigation:

- `unit/`: pure function and module-level tests with mocked network calls.
- `integration/`: tests that exercise a larger workflow across modules.
- `data/`: small static fixtures used by tests.

## Rules

- Do not call live publisher, Crossref, or OpenAlex services in normal tests.
- Mock network responses unless a test is explicitly marked as external.
- Keep tests focused on real invariants: queue behavior, path resolution,
  metadata fallback, filename safety, PDF validation, and command-line routing.
```

- [ ] **Step 4: Create `data/GUIDE_data.md`**

Write:

```markdown
# GUIDE_data

## Purpose

`data/` stores reusable working data used by the pipeline.

## Contents

- `interim/doi_queues/`: DOI queue files and adjacent success/error ledgers.

## Rules

- Put mutable DOI queues and ledgers here.
- Do not put downloaded PDFs here.
- Do not put final metadata exports here.
- Keep large or private research data out of git unless explicitly approved.
```

- [ ] **Step 5: Create `outputs/GUIDE_outputs.md`**

Write:

```markdown
# GUIDE_outputs

## Purpose

`outputs/` stores generated artifacts produced by command-line runs.

## Contents

- `metadata/`: exported article metadata CSV files.
- `pdfs/`: downloaded article PDFs.
- `runs/`: future audit reports, diagnostics, and run summaries.

## Rules

- Generated outputs should be reproducible from configuration plus DOI queues
  whenever possible.
- Keep large PDFs and private outputs out of git unless explicitly approved.
- Use `outputs/runs/` for future coverage reports and base-URL diagnostics.
```

- [ ] **Step 6: Create `docs/GUIDE_docs.md`**

Write:

```markdown
# GUIDE_docs

## Purpose

`docs/` contains documentation that is more detailed than the root README.

## Contents

- `user/`: user-facing explanations, reviews, and workflow notes.
- `reference/`: developer and AI ground-truth about architecture, structure,
  data formats, and operational assumptions.

## Rules

- Put user-facing prose in `docs/user/`.
- Put stable technical reference material in `docs/reference/`.
- Keep root `README.md` concise and link deeper docs from there.
```

---

### Task 5: Add Structure Reference Documentation

**Files:**
- Create: `docs/reference/structure.md`

- [ ] **Step 1: Create the reference directory**

Run:

```bash
mkdir -p docs/reference
```

Expected: `docs/reference/` exists.

- [ ] **Step 2: Create `docs/reference/structure.md`**

Write:

```markdown
# Project Structure Reference

This document explains where files belong in `paper-downloader`.

## Pipeline Folders

The project pipeline is:

```text
ISSN -> DOI queue -> metadata CSV -> PDF downloads
```

`ISSN` means International Standard Serial Number. It identifies a journal.
`DOI` means Digital Object Identifier. It identifies an article or other
scholarly work.

The folder mapping is:

| Pipeline stage | Folder | Meaning |
| --- | --- | --- |
| Implementation code | `src/paper_downloader/` | Python package and command-line implementation |
| DOI queue and ledgers | `data/interim/doi_queues/` | Mutable working files used to resume batches |
| Metadata exports | `outputs/metadata/` | Generated CSV files for article screening |
| PDF downloads | `outputs/pdfs/` | Generated downloaded PDF files |
| Run reports | `outputs/runs/` | Future diagnostics, audit reports, and run summaries |

## Root Files

- `README.md`: user-facing overview and quick start.
- `config.toml`: default runtime settings.
- `pyproject.toml`: package metadata, dependencies, scripts, pytest settings,
  and setuptools configuration.
- `GUIDE_ROOT.md`: root-level developer guide.
- `GUIDE_OVERVIEW.md`: high-level architecture and data-flow guide.

## Generated Artifacts

Generated PDFs and large outputs should normally stay out of git. Small sample
DOI queues or metadata files may be tracked only when they are intentionally
kept as examples.
```

---

### Task 6: Update User And Developer Documentation

**Files:**
- Modify: `README.md`
- Modify: `GUIDE_ROOT.md`
- Modify: `GUIDE_OVERVIEW.md`

- [ ] **Step 1: Replace old DOI paths in `README.md`**

Replace examples like:

```text
dois/1467-9965_dois.txt
```

with:

```text
data/interim/doi_queues/1467-9965_dois.txt
```

Replace examples like:

```text
metadata/1467-9965_metadata.csv
```

with:

```text
outputs/metadata/1467-9965_metadata.csv
```

Replace examples like:

```text
pdfs/1467-9965/<YEAR>/...pdf
```

with:

```text
outputs/pdfs/1467-9965/<YEAR>/...pdf
```

- [ ] **Step 2: Update README configuration descriptions**

Ensure the `config.toml` path bullets say:

```markdown
- `dois_dir`: working folder for DOI queue files and ledger files
- `metadata_dir`: output folder for metadata CSV files
- `pdfs_dir`: output folder for downloaded PDFs
```

- [ ] **Step 3: Update `GUIDE_ROOT.md` code references**

Replace references to `paper_downloader/...` with `src/paper_downloader/...`.

Replace generated path examples:

```text
dois/<issn>_dois.txt
metadata/<issn>_metadata.csv
pdfs/
```

with:

```text
data/interim/doi_queues/<issn>_dois.txt
outputs/metadata/<issn>_metadata.csv
outputs/pdfs/
```

- [ ] **Step 4: Update `GUIDE_OVERVIEW.md` project tree**

The tree should include:

```text
paper-downloader/
├── config.toml
├── data/
│   ├── GUIDE_data.md
│   └── interim/
│       └── doi_queues/
├── docs/
│   ├── GUIDE_docs.md
│   ├── reference/
│   │   └── structure.md
│   └── user/
│       └── project-review.md
├── outputs/
│   ├── GUIDE_outputs.md
│   ├── metadata/
│   ├── pdfs/
│   └── runs/
├── src/
│   ├── GUIDE_src.md
│   └── paper_downloader/
│       ├── GUIDE_paper_downloader.md
│       ├── __init__.py
│       ├── _http.py
│       ├── browser.py
│       ├── cli.py
│       ├── doi_sources.py
│       ├── downloader.py
│       ├── metadata_export.py
│       ├── naming.py
│       └── progress.py
├── tests/
│   ├── GUIDE_tests.md
│   ├── test_cli.py
│   ├── test_doi_sources.py
│   ├── test_downloader.py
│   ├── test_metadata_export.py
│   ├── test_naming.py
│   └── test_progress.py
├── GUIDE_OVERVIEW.md
├── GUIDE_ROOT.md
├── pyproject.toml
└── README.md
```

---

### Task 7: Fix Tests After The Move

**Files:**
- Modify: tests only if failures show path assumptions

- [ ] **Step 1: Run the full test suite**

Run:

```bash
uv run pytest
```

Expected: all tests pass. If imports fail, confirm `pyproject.toml` has `pythonpath = ["src"]`.

- [ ] **Step 2: Search for hard-coded old paths**

Run:

```bash
rg "paper_downloader/|dois/|metadata/|pdfs/" README.md GUIDE_ROOT.md GUIDE_OVERVIEW.md docs tests src config.toml pyproject.toml
```

Expected: any remaining matches are either intentional explanatory examples or should be updated to the new paths.

- [ ] **Step 3: Update failing path expectations**

If a test expects `dois/<name>`, change it to expect `data/interim/doi_queues/<name>` only when that expectation comes from the default config. Do not change tests that intentionally use temporary directories supplied by the test itself.

Example expectation update:

```python
expected_doi_path = tmp_path / "data" / "interim" / "doi_queues" / "1467-9965_dois.txt"
```

Use the actual surrounding test variable names from the existing test file.

- [ ] **Step 4: Re-run focused failing tests**

Run the smallest failing test file first. Example:

```bash
uv run pytest tests/test_cli.py -q
```

Expected: the focused file passes.

- [ ] **Step 5: Re-run the full suite**

Run:

```bash
uv run pytest
```

Expected: all tests pass.

---

### Task 8: Verify Commands, Linting, And Final Tree

**Files:**
- Modify: none unless verification exposes a real issue

- [ ] **Step 1: Run command-line smoke checks**

Run:

```bash
uv run paper-downloader --help
uv run paper-issn-to-doi --help
uv run paper-export-metadata --help
uv run paper-download --help
```

Expected: every command prints help text and exits successfully.

- [ ] **Step 2: Run linting**

Run:

```bash
uv run ruff check .
```

Expected: no lint errors.

- [ ] **Step 3: Review the final tree**

Run:

```bash
find . -maxdepth 3 -type d -not -path './.git*' -not -path './.venv*' | sort
```

Expected: the tree includes `src/`, `data/interim/doi_queues/`, `outputs/metadata/`, `outputs/pdfs/`, `outputs/runs/`, `docs/reference/`, and `tests/`.

- [ ] **Step 4: Review changed files**

Run:

```bash
git diff --stat
git diff -- pyproject.toml config.toml README.md GUIDE_ROOT.md GUIDE_OVERVIEW.md docs/reference/structure.md
```

Expected: diffs show only the intended structure, config, and documentation changes.

---

### Task 9: Commit The Restructure

**Files:**
- Stage all intentional restructure changes

- [ ] **Step 1: Stage the work**

Run:

```bash
git add .
```

Expected: all intended changes are staged.

- [ ] **Step 2: Confirm staged files**

Run:

```bash
git status --short
```

Expected: staged rename entries for the package move, staged docs/config updates, and no accidental edits to `mynotes.md`.

- [ ] **Step 3: Commit**

Run:

```bash
git commit -m "refactor: align project structure"
```

Expected: one commit records the structure alignment.

---

## Self-Review

- Spec coverage: The plan covers the `AGENTS.md` structure requirements for `src/`, `tests/`, `data/`, `outputs/`, `docs/`, root guides, folder guides, verification, and commit discipline.
- Placeholder scan: The plan avoids `TBD`, `TODO`, and vague "handle edge cases" steps. Each file creation task includes concrete content.
- Type consistency: No new Python application interfaces are introduced. The only Python packaging interface change is setuptools `package-dir = {"" = "src"}` and pytest `pythonpath = ["src"]`.

## Execution Options

1. **Subagent-Driven:** dispatch a fresh worker per task and review between tasks.
2. **Inline Execution:** execute the tasks in this session with checkpoints.

Because this restructure touches many paths and the workspace is already dirty, prefer inline execution unless the existing dirty changes are first committed or stashed by the user.
