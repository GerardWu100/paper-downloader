# Architecture Hardening And Bug Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Find real defects, reduce architectural coupling, and make `paper-downloader` easier to extend without turning the small command-line tool into a framework.

**Architecture:** Keep the documented user workflow stable: `ISSN -> DOI queue -> metadata CSV -> PDF downloads`. Split the current large modules along real responsibilities: configuration, DOI identity, provider clients, metadata extraction, PDF resolution, transport, storage, and batch progress. Fix behavior with tests first, then refactor behind the command-line interface.

**Tech Stack:** Python 3.11+, `uv`, `pytest`, `ruff`, standard-library HTTP for now, Playwright only for browser mode.

---

## Baseline Evidence

Commands run before writing this plan:

```bash
uv run pytest
uv run ruff check .
```

Result:

- `pytest`: 60 passed.
- `ruff`: all checks passed.

This means the current suite is green. The concern is not that the project is obviously broken; the concern is that important edge cases are not covered and the module boundaries make future changes risky.

## Current Architecture Critique

### What Is Good

- The project has a sensible `src/` layout and importable package.
- The workflow is cleanly documented as `ISSN -> DOI queue -> metadata CSV -> PDF downloads`.
- The intermediate DOI queue is a good research artifact. It lets the user inspect, edit, resume, and reuse work.
- Tests mock network calls instead of hitting Crossref, OpenAlex, or publishers.
- Generated outputs are separated into `data/` and `outputs/`, which keeps implementation code cleaner.

### What Is Weak

- `src/paper_downloader/downloader.py` is a god module. It owns URL building, HTTP transport, HTML parsing, PDF validation, filename choice, metadata lookup, output path creation, retry loops, progress printing, and batch state.
- `src/paper_downloader/cli.py` mixes argument parsing, TOML loading, `.env` loading, path resolution, config merging, and orchestration.
- Crossref and OpenAlex fetching logic is duplicated between `metadata_export.py`, `naming.py`, and `doi_sources.py`.
- DOI identity is just a raw string everywhere. That makes case sensitivity, marker generation, deduplication, and URL encoding easy to handle inconsistently.
- The ledger format is ad hoc text. It is readable, but the parser and writer are tightly coupled to string conventions.
- Browser mode starts Playwright and a browser for each URL attempt instead of having a batch-level browser transport lifecycle.
- The HTTP layer has no shared retry, status handling, rate-limit handling, or structured error taxonomy.
- Tests are good for the current behavior but weak on failure modes: corrupt existing PDFs, stale ledgers, invalid config values, DOI case normalization, browser recursion depth, and concurrent ledger writes.

## Potential Bugs To Verify First

1. **Stale success ledger is retried but not re-recorded after success.**
   In `progress.reconcile_pending_dois`, stale successes are placed back into `pending_dois`. In `progress.record_batch_outcome`, success recording returns early when the DOI is already in `successful_dois`. A DOI that had a stale success ledger but no PDF can be downloaded again, yet the success row may not get a fresh `pdf=` field.

2. **Existing PDF detection trusts filename markers without validating bytes.**
   `naming.collect_completed_doi_suffixes` treats any `*.pdf` with a DOI marker as complete. A zero-byte or HTML file renamed to `.pdf` can make the downloader skip a DOI.

3. **DOI normalization is case-sensitive.**
   DOI values are operationally case-insensitive for identity, but `doi_sources.normalize_doi` preserves case. `10.1000/ABC` and `10.1000/abc` can become two queue entries or two different filename markers.

4. **Invalid numeric config values are not rejected at the boundary.**
   `crossref_rows = 0`, negative rows, or `timeout_seconds = 0` can flow into API requests and pagination decisions. This should fail early with a clear config error.

5. **Browser resolver depth differs from direct HTTP resolver depth.**
   Direct HTTP stops when `depth >= PDF_RESOLUTION_MAX_DEPTH`; browser mode stops when `depth > PDF_RESOLUTION_MAX_DEPTH`. That is an off-by-one inconsistency.

6. **Ledger appends are not locked.**
   Queue and log rewrite functions use `fcntl` locks, but `append_progress_entry` does not. Two processes can interleave ledger writes.

7. **Browser mode is too expensive for batches.**
   `fetch_binary_response_via_browser` opens Playwright, launches a browser, creates a context, resolves one URL, then closes everything. For a large DOI queue this is slow and fragile.

## Target File Structure

Refactor toward this structure only as tasks touch the relevant behavior:

```text
src/paper_downloader/
├── cli.py
├── config.py
├── models.py
├── providers/
│   ├── __init__.py
│   ├── crossref.py
│   └── openalex.py
├── metadata/
│   ├── __init__.py
│   ├── extraction.py
│   └── export.py
├── download/
│   ├── __init__.py
│   ├── batch.py
│   ├── html_resolver.py
│   ├── service.py
│   ├── storage.py
│   └── transport.py
├── browser.py
├── naming.py
└── progress.py
```

Keep `browser.py`, `naming.py`, and `progress.py` temporarily at the package root until the tests around them are stronger. Move code gradually; do not perform a big-bang rewrite.

## Implementation Tasks

### Task 1: Add Regression Tests For Suspected Bugs

**Files:**

- Modify: `tests/test_progress.py`
- Modify: `tests/test_naming.py`
- Modify: `tests/test_doi_sources.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_downloader.py`
- Modify: `tests/test_browser.py` if browser-specific tests become too large for `tests/test_downloader.py`

- [ ] **Step 1: Add a stale-success retry test**

Add a test showing that a DOI in `*_successful.txt` but missing from the PDF folder is retried and gets a fresh success row with `pdf=`.

Run:

```bash
uv run pytest tests/test_downloader.py::test_stale_success_retry_records_fresh_pdf_path -v
```

Expected before fix: fail because the success writer returns early.

- [ ] **Step 2: Add a corrupt existing PDF marker test**

Add a test where `outputs/pdfs/paper__doi_10.1__foo.pdf` exists but contains invalid bytes. The DOI must remain pending.

Run:

```bash
uv run pytest tests/test_progress.py::test_reconcile_pending_dois_does_not_trust_corrupt_existing_pdf -v
```

Expected before fix: fail because filename marker alone is trusted.

- [ ] **Step 3: Add a DOI case normalization test**

Add a test proving that `https://doi.org/10.1000/ABC` and `10.1000/abc` collapse to one canonical DOI.

Run:

```bash
uv run pytest tests/test_doi_sources.py::test_normalize_doi_list_lowercases_for_identity -v
```

Expected before fix: fail because case is preserved.

- [ ] **Step 4: Add invalid config tests**

Add tests for `crossref_rows = 0`, `crossref_rows = -1`, `timeout_seconds = 0`, and `timeout_seconds = -1`.

Run:

```bash
uv run pytest tests/test_cli.py::test_load_config_rejects_non_positive_numeric_settings -v
```

Expected before fix: fail because config loading accepts invalid values.

- [ ] **Step 5: Add browser depth parity test**

Add a test that direct HTTP and browser mode both stop at the same resolver depth.

Run:

```bash
uv run pytest tests/test_downloader.py::test_browser_and_http_pdf_resolution_use_same_depth_limit -v
```

Expected before fix: fail because browser mode allows one extra level.

- [ ] **Step 6: Run all tests**

Run:

```bash
uv run pytest
```

Expected: new tests fail; existing tests remain understandable.

### Task 2: Centralize DOI Identity

**Files:**

- Create: `src/paper_downloader/models.py`
- Modify: `src/paper_downloader/doi_sources.py`
- Modify: `src/paper_downloader/progress.py`
- Modify: `src/paper_downloader/naming.py`
- Modify: affected tests

- [ ] **Step 1: Create a small DOI normalization module**

Add `models.py` with a `normalize_doi` function and a `Doi` dataclass only if the dataclass reduces repeated string handling. The normalization rule should strip DOI URL prefixes, trim whitespace, and lowercase the DOI for identity.

- [ ] **Step 2: Route all existing DOI normalization through `models.py`**

Replace local DOI normalization in `doi_sources.py`, `progress.py`, and filename marker helpers with the shared normalization function.

- [ ] **Step 3: Preserve display strings intentionally**

If a DOI is displayed or written to output, use the normalized canonical DOI. Avoid carrying both raw and canonical DOI values unless a test proves the raw value matters.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/test_doi_sources.py tests/test_progress.py tests/test_naming.py -v
uv run ruff check .
```

Expected: DOI case tests pass; filename marker tests still pass with lowercased markers.

- [ ] **Step 5: Commit**

```bash
git add src/paper_downloader/models.py src/paper_downloader/doi_sources.py src/paper_downloader/progress.py src/paper_downloader/naming.py tests
git commit -m "fix: centralize doi normalization"
```

### Task 3: Fix Resume And Existing-PDF Validation

**Files:**

- Modify: `src/paper_downloader/naming.py`
- Modify: `src/paper_downloader/progress.py`
- Modify: `src/paper_downloader/downloader.py`
- Modify: affected tests

- [ ] **Step 1: Validate completed PDF candidates**

Change completed-PDF scanning so a file only counts as completed when it has a DOI marker and valid PDF bytes. Use the existing `PDF_MAGIC_PREFIX` rule or move the PDF-byte validation into a small shared function without importing the whole downloader from naming.

- [ ] **Step 2: Handle stale success rows explicitly**

When `ResumeDecisions.stale_success_dois` is not empty, remove those DOI values from the in-memory `successful_dois` set before retrying. After a successful retry, write a fresh success row with `status=success`, `ts=...`, and `pdf=...`.

- [ ] **Step 3: Lock ledger appends**

Add the same `fcntl` locking discipline to `append_progress_entry` that rewrite functions already use.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/test_progress.py tests/test_downloader.py -v
uv run ruff check .
```

Expected: stale-ledger and corrupt-PDF tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/paper_downloader/naming.py src/paper_downloader/progress.py src/paper_downloader/downloader.py tests
git commit -m "fix: harden resume reconciliation"
```

### Task 4: Extract And Validate Configuration

**Files:**

- Create: `src/paper_downloader/config.py`
- Modify: `src/paper_downloader/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `README.md`
- Modify: `GUIDE_ROOT.md`
- Modify: `src/paper_downloader/GUIDE_paper_downloader.md`

- [ ] **Step 1: Move `AppConfig`, `.env` loading, base URL parsing, path resolution, and config validation into `config.py`**

`cli.py` should parse arguments and call orchestration functions. It should not own TOML parsing.

- [ ] **Step 2: Add boundary validation**

Reject:

- non-positive `crossref_rows`
- non-positive `timeout_seconds`
- empty email when a Crossref command is run
- invalid `doi_files` values that are not strings
- configured browser path that exists but is not a file

- [ ] **Step 3: Keep CLI behavior documented**

Keep documented commands working:

```bash
uv run paper-issn-to-doi --issn 1467-9965 --rows 1
uv run paper-export-metadata --dois-file tests/data/sample_dois.txt
uv run paper-download --doi 10.1000/example --base-url https://publisher.example/pdf
```

Use mocked or temporary test data where live network access would otherwise be needed.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/test_cli.py -v
uv run pytest
uv run ruff check .
```

Expected: config tests pass and all old CLI tests still pass.

- [ ] **Step 5: Commit**

```bash
git add src/paper_downloader/config.py src/paper_downloader/cli.py tests/test_cli.py README.md GUIDE_ROOT.md src/paper_downloader/GUIDE_paper_downloader.md
git commit -m "refactor: isolate configuration loading"
```

### Task 5: Split Provider Clients From Metadata Extraction

**Files:**

- Create: `src/paper_downloader/providers/__init__.py`
- Create: `src/paper_downloader/providers/crossref.py`
- Create: `src/paper_downloader/providers/openalex.py`
- Create: `src/paper_downloader/metadata/__init__.py`
- Create: `src/paper_downloader/metadata/extraction.py`
- Create: `src/paper_downloader/metadata/export.py`
- Modify: `src/paper_downloader/metadata_export.py`
- Modify: `src/paper_downloader/naming.py`
- Modify: `src/paper_downloader/doi_sources.py`
- Modify: affected tests
- Add: `src/paper_downloader/providers/GUIDE_providers.md`
- Add: `src/paper_downloader/metadata/GUIDE_metadata.md`

- [ ] **Step 1: Move provider URL construction and JSON fetching into provider modules**

`crossref.py` should know Crossref URLs, polite-pool email headers, and Crossref payload shape. `openalex.py` should know OpenAlex URLs and source/work payload shape.

- [ ] **Step 2: Move field extraction into `metadata/extraction.py`**

Keep pure extraction functions separate from network calls. Pure functions are easier to test with sample payloads.

- [ ] **Step 3: Make `metadata_export.py` a compatibility shim or remove it**

If console scripts still import `paper_downloader.metadata_export`, keep a thin wrapper that delegates to `metadata.export`. Otherwise update imports and remove the old file in the same commit.

- [ ] **Step 4: Make naming use the same provider clients**

`naming.lookup_doi_metadata` should not reimplement Crossref/OpenAlex URL logic. It should call the provider layer or a small metadata service.

- [ ] **Step 5: Verify**

Run:

```bash
uv run pytest tests/test_metadata_export.py tests/test_naming.py tests/test_doi_sources.py -v
uv run pytest
uv run ruff check .
```

Expected: metadata behavior is unchanged, but provider URL construction lives in one place.

- [ ] **Step 6: Commit**

```bash
git add src/paper_downloader tests GUIDE_ROOT.md src/paper_downloader/GUIDE_paper_downloader.md
git commit -m "refactor: separate provider clients from extraction"
```

### Task 6: Split Download Runtime Into Focused Units

**Files:**

- Create: `src/paper_downloader/download/__init__.py`
- Create: `src/paper_downloader/download/transport.py`
- Create: `src/paper_downloader/download/html_resolver.py`
- Create: `src/paper_downloader/download/storage.py`
- Create: `src/paper_downloader/download/service.py`
- Create: `src/paper_downloader/download/batch.py`
- Add: `src/paper_downloader/download/GUIDE_download.md`
- Modify: `src/paper_downloader/downloader.py`
- Modify: `src/paper_downloader/browser.py`
- Modify: affected tests

- [ ] **Step 1: Move HTTP response and fetcher code into `download/transport.py`**

Move `BinaryHttpResponse`, `fetch_binary_response`, and transport-related constants. Add structured exceptions for timeout, HTTP status, invalid content, and incomplete reads.

- [ ] **Step 2: Move HTML PDF resolution into `download/html_resolver.py`**

Move candidate regexes, candidate URL normalization, candidate extraction, and recursive resolver. Keep browser and direct HTTP using the same depth rule.

- [ ] **Step 3: Move PDF save logic into `download/storage.py`**

Move byte validation, output directory construction, temporary path construction, filename assembly, and atomic replace.

- [ ] **Step 4: Move one-DOI orchestration into `download/service.py`**

`download_one_doi` should read like a short workflow: build URLs, choose transport, resolve response, save PDF, return result.

- [ ] **Step 5: Move batch loops into `download/batch.py`**

Move `run_download_pass` and `run_download_batch`. Keep progress reconciliation calls here.

- [ ] **Step 6: Keep `downloader.py` temporarily as a re-export facade**

Re-export public names used by tests and CLI, then remove the facade only after imports are migrated.

- [ ] **Step 7: Verify after each move**

Run after each substep:

```bash
uv run pytest tests/test_downloader.py -v
uv run ruff check .
```

Run at the end:

```bash
uv run pytest
```

Expected: no behavior change except bug fixes already covered in earlier tasks.

- [ ] **Step 8: Commit**

```bash
git add src/paper_downloader tests
git commit -m "refactor: split download runtime"
```

### Task 7: Improve Browser Transport Lifecycle

**Files:**

- Modify: `src/paper_downloader/browser.py`
- Modify: `src/paper_downloader/download/transport.py`
- Modify: `src/paper_downloader/download/service.py`
- Modify: `src/paper_downloader/download/batch.py`
- Modify: affected tests

- [ ] **Step 1: Add a browser transport object**

Create a small class or context manager that opens Playwright once per batch, keeps one browser context, and exposes `fetch(download_url) -> BinaryHttpResponse`.

- [ ] **Step 2: Use the transport object in browser batches**

When `use_browser = true`, `run_download_batch` should create the browser transport once and pass it through DOI attempts.

- [ ] **Step 3: Keep direct HTTP lightweight**

Direct HTTP should still avoid importing Playwright.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/test_downloader.py -v
uv run pytest
uv run ruff check .
```

Expected: direct mode tests do not require Playwright browser installation; browser-mode unit tests mock the transport.

- [ ] **Step 5: Commit**

```bash
git add src/paper_downloader tests
git commit -m "refactor: reuse browser transport per batch"
```

### Task 8: Add A Download Audit Report Foundation

**Files:**

- Create: `src/paper_downloader/audit.py`
- Modify: `src/paper_downloader/cli.py`
- Modify: `README.md`
- Modify: `docs/reference/structure.md`
- Modify: `GUIDE_ROOT.md`
- Add: tests for audit summaries

- [ ] **Step 1: Define an audit summary dataclass**

Track counts for source DOIs, pending DOIs, success-ledger DOIs, error-ledger DOIs, existing valid PDFs, corrupt marked PDFs, and missing PDFs after success.

- [ ] **Step 2: Add an internal audit function**

Given one DOI queue file and one PDF root, return the summary without network calls.

- [ ] **Step 3: Add a CLI command only if the internal API is clean**

Command:

```bash
uv run paper-downloader audit --dois-file data/interim/doi_queues/1467-9965_dois.txt
```

Output should be plain text first. Save HTML later only if needed.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/test_audit.py -v
uv run pytest
uv run ruff check .
```

Expected: audit works without network and identifies corrupt marked PDFs.

- [ ] **Step 5: Commit**

```bash
git add src/paper_downloader tests README.md docs/reference/structure.md GUIDE_ROOT.md
git commit -m "feat: add download audit summary"
```

## Verification Checklist For The Full Branch

- [ ] Run unit and integration tests:

```bash
uv run pytest
```

- [ ] Run linting:

```bash
uv run ruff check .
```

- [ ] Run practical CLI smoke tests with toy files:

```bash
mkdir -p /tmp/paper-downloader-smoke
printf "10.1000/example\n" > /tmp/paper-downloader-smoke/example_dois.txt
uv run paper-export-metadata --dois-file /tmp/paper-downloader-smoke/example_dois.txt --output-csv /tmp/paper-downloader-smoke/metadata.csv
uv run paper-download --doi 10.1000/example --base-url https://publisher.example/pdf
```

The metadata command may write blank metadata if providers are unavailable; the download command is expected to fail against `publisher.example`, but it must fail with a clear message and no traceback for normal operator mistakes.

- [ ] Update developer guides:

```text
GUIDE_ROOT.md
GUIDE_OVERVIEW.md
src/GUIDE_src.md
src/paper_downloader/GUIDE_paper_downloader.md
tests/GUIDE_tests.md
docs/reference/structure.md
```

- [ ] Commit final documentation updates:

```bash
git add README.md GUIDE_ROOT.md GUIDE_OVERVIEW.md src/GUIDE_src.md src/paper_downloader/GUIDE_paper_downloader.md tests/GUIDE_tests.md docs/reference/structure.md
git commit -m "docs: update architecture guides"
```

## Recommended Execution Order

1. Fix bug coverage first.
2. Centralize DOI identity.
3. Harden resume behavior.
4. Extract config.
5. Extract provider clients.
6. Split download runtime.
7. Improve browser lifecycle.
8. Add audit reporting.

Do not start with a full folder reshuffle. Start with bug tests and the DOI model, because those give the rest of the refactor a stable meaning for identity and completion.

## What Else?

- The biggest hidden risk is not a syntax bug; it is silent false completion. A corrupt PDF marker or stale ledger can make the tool believe work is done when it is not.
- The second biggest risk is provider drift. Crossref and OpenAlex payloads change shape over time, so extraction code should be isolated and tested with fixture payloads.
- The browser mode should remain optional. If browser automation becomes central, this project will drift from a small downloader into a publisher automation framework.
- Add publisher adapters only after the generic downloader has audit reports. Without diagnostics, adapters will hide rather than explain failures.

## TL;DR

The project is not bad; it is junior in the predictable places: too much responsibility in large modules, raw strings for important identities, weak boundary validation, and incomplete failure-mode tests. Fix the likely bugs first, then split the architecture behind the current command-line workflow.
