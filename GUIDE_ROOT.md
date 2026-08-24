# GUIDE_ROOT

## Part 1: Conceptual explanation

`paper-downloader/` is a standalone ISSN-to-PDF downloader.

The core workflow has two stages:

1. **ISSN to DOI collection**
   One ISSN identifies a journal. The project queries two metadata providers,
   OpenAlex and Crossref, to collect every article DOI it can find for that
   journal. The merged DOI set is written to
   `data/interim/doi_queues/<issn>_dois.txt`.
2. **DOI file to metadata export**
   A separate metadata-export module consumes one DOI queue file or a
   config-defined list of DOI queue files and queries Crossref plus OpenAlex
   for article metadata such as title, abstract, authors, ORCID IDs,
   affiliations, published date, journal title, publisher, keywords, and
   topics. The flat result is written to
   `outputs/metadata/<issn>_metadata.csv`. The
   exporter uses bounded parallel workers for network lookups, preserves DOI
   queue order in the CSV, spaces request starts per API host to reduce
   throttling, and prints per-DOI terminal progress so long network-bound runs
   do not appear hung.
3. **DOI file to PDF download**
   The downloader consumes either one DOI value, one DOI text file, or a
   config-defined list of DOI text files. For each DOI, it builds one or more
   direct HTTP URLs from `.env` or CLI-provided base URLs: `base_url/<doi>`.
   For each DOI, it picks one random starting base URL, then exhausts the
   remaining base URLs in wrapped order, downloads the response, verifies that
   it is a real PDF, resolves simple HTML viewer pages into the real PDF URL
   when possible, resolves a readable title from Crossref or OpenAlex, and
   saves the file under `outputs/pdfs/` with a DOI marker in the filename.

The downloader is resumable.

- The DOI queue file is mutable.
- Successes are appended to `*_successful.txt`.
- Failures are appended to `*_errors.txt`.
- DOI values that fail in the current queue get one automatic second pass after
  the queue is exhausted.
- If a retry succeeds, that DOI row is removed from `*_errors.txt`.
- Older DOI values already recorded in `*_errors.txt` are skipped on later
  resumed runs unless the operator passes `--retry-error-dois`.
- Existing PDFs are detected by scanning for the `__doi_...` marker in saved
  filenames and validating that the file bytes start like a real PDF.
- The marker is unique per DOI. A slash becomes `__` and any character the
  filesystem rejects becomes `_`, so `10.1111/mafi.12108` reads back plainly as
  `__doi_10.1111__mafi.12108`. When that substitution would let two different
  DOIs share one marker, for example `10.1111/mafi:12108` against
  `10.1111/mafi_12108`, a short digest of the DOI is appended to the second one.
  Without it, resume would treat a DOI it never downloaded as already complete
  and skip it on every later run.
- Temporary `.partial_*` files from a run that died mid-write are swept at the
  start of each resumable batch.
- Multiple base URLs can be configured in `.env`, and the downloader picks one
  random starting URL per DOI before exhausting the rest of the list.
- The batch runner sleeps between DOI downloads using the configured
  `inter_download_sleep_seconds` value, which defaults to 3 seconds.

This is intentionally similar to the queue and naming model used in
`one-time-projects/education-scraper`, including the operational separation
between "build the DOI file" and "consume the DOI file." The implementation
stays small by keeping the download path on direct HTTP.

### Flow sketch

```text
ISSN
  |
  +--> DOI file builder
  |       |
  |       +--> OpenAlex source lookup
  |       |
  |       +--> OpenAlex works cursor pagination
  |       |
  |       +--> Crossref works cursor pagination
  |               |
  |               +--> merged DOI queue file
  |
  +--> metadata exporter reads DOI queue file
  |       |
  |       +--> Crossref work lookup per DOI
  |       |
  |       +--> OpenAlex work lookup per DOI
  |               |
  |               +--> metadata CSV
  |
  +--> downloader reads DOI queue file
          |
          +--> direct HTTP for base_url/<doi>
                    |
                    +--> HTML viewer-page resolution when possible
                    +--> PDF validation
                    +--> metadata title lookup
                    +--> DOI-tagged saved PDF
                    +--> success/error ledger update
```

## Part 2: Code reference

- `pyproject.toml`: package metadata, console script entrypoint, and dev tools.
- `.env`: local base-URL list such as `PAPER_DOWNLOADER_BASE_URLS=...`.
  The loader normalizes messy entries by defaulting missing schemes to
  `https` and trimming trailing `/`.
- `config.toml`: default runtime settings such as `base_url`, `email`, output
  folders, timeout, inter-download sleep, and DOI queue files. Numeric request
  bounds, removed browser settings, and configured directory collisions are
  validated when config loads.
- `README.md`: user-facing usage guide.
- `docs/user/project-review.md`: user-facing review of the current feature set,
  design choices, limitations, and recommended next features.
- `GUIDE_ROOT.md`: developer guide for this project root.
- `GUIDE_OVERVIEW.md`: high-level system overview.
- `src/paper_downloader/__init__.py`: package exports.
- `src/paper_downloader/cli.py`: subcommand parsing, DOI-file generation,
  metadata export, PDF-download orchestration, and local audit command routing.
  It also backs the `paper-issn-to-doi`, `paper-export-metadata`,
  `paper-download`, and `paper-downloader` Python entrypoints.
- `src/paper_downloader/config.py`: TOML loading, `.env` loading, base URL
  normalization, path resolution, and config validation.
- `src/paper_downloader/models.py`: shared DOI identity normalization.
- `src/paper_downloader/audit.py`: no-network queue, ledger, and PDF audit
  summaries.
- `src/paper_downloader/providers/`: Crossref and OpenAlex URL construction,
  plus the Crossref timed JSON helper used by metadata export.
- `src/paper_downloader/metadata/`: metadata extraction and CSV export
  implementation.
- `src/paper_downloader/doi_sources.py`: OpenAlex and Crossref API queries, DOI
  normalization, DOI queue-file writing, and repeated-cursor guards so
  pagination cannot loop forever if an upstream API repeats one cursor token.
- `src/paper_downloader/naming.py`: DOI metadata lookup, title sanitization,
  generic filename detection, DOI-marker helpers, and merged metadata fallback
  logic that can combine Crossref title with OpenAlex year when needed.
- `src/paper_downloader/progress.py`: DOI queue loading, ledger parsing, queue
  rewriting, and resume reconciliation.
- `src/paper_downloader/downloader.py`: direct HTTP PDF download, HTML viewer-page
  resolution, output-path selection, filename inference that drops
  URL-encoded path separators, save logic that treats metadata as optional
  after PDF validation, and batch execution.
- `tests/test_doi_sources.py`: unit tests for ISSN-to-DOI collection.
- `tests/test_cli.py`: unit tests for `.env` loading and base-URL parsing.
- `tests/test_audit.py`: unit tests for local audit summaries.
- `tests/test_metadata_export.py`: unit tests for metadata field extraction
  and CSV export.
- `tests/test_naming.py`: unit tests for metadata lookup and filename logic.
- `tests/test_progress.py`: unit tests for queue and ledger behavior.
- `tests/test_downloader.py`: unit and small integration tests for direct PDF
  downloads and end-to-end ISSN batch flow with mocked HTTP calls.

Where to start:

1. Read `src/paper_downloader/cli.py` for the top-level control flow.
2. Read `src/paper_downloader/doi_sources.py` for ISSN-to-DOI collection.
3. Read `src/paper_downloader/metadata/export.py` for DOI-to-CSV export.
4. Read `src/paper_downloader/downloader.py` for DOI-to-PDF saving.

## Part 3: Short journal

- 2026-04-08: Kept the DOI queue and filename marker model from `education-scraper`, restored the explicit DOI-file workflow, and kept browser automation disabled by default while adding an optional Playwright browser mode that reuses an installed system browser instead of requiring a bundled Chromium download.
- 2026-04-08: Added per-DOI terminal progress lines to metadata export so `paper-export-metadata` shows visible activity during long API-bound runs.
- 2026-04-08: Normalized configured PDF base URLs so `.env`, `config.toml`, and CLI entries tolerate missing `https://` prefixes and trailing `/` characters before download URL construction.
- 2026-04-08: Added `config.toml` support for `doi_file` and `doi_files` so `paper-download` can run unattended across one or more DOI queue files without repeating `--dois-file`.
- 2026-04-08: Reused `doi_file` and `doi_files` for metadata export and moved default metadata CSV output into `outputs/metadata/` instead of the DOI queue folder.
- 2026-04-08: Clarified in the root guide and README that resumed downloads skip DOI values already logged in `*_errors.txt` unless `--retry-error-dois` is supplied.
- 2026-04-08: Removed configurable DOI-path encoding so DOI slashes are always preserved, and changed `use_browser` from an HTTP fallback into an explicit browser-only download mode.
- 2026-04-08: Added one automatic second pass for DOI values that fail in the current queue, removed recovered DOI rows from `*_errors.txt`, and retried transient `IncompleteRead` HTTP body failures.
- 2026-04-08: Randomized the first base URL tried for each DOI while still exhausting the full URL list.
- 2026-04-08: Removed randomized inter-DOI sleep configuration and fixed the delay at 3 seconds between DOI downloads.
- 2026-04-08: Added repeated-cursor guards in OpenAlex and Crossref DOI pagination, fixed nested HTML resolver referer propagation, merged Crossref/OpenAlex year fallback in DOI metadata lookup, and made metadata export continue after per-DOI failures by writing blank fallback rows.
- 2026-04-25: Made PDF saves resilient to metadata-provider outages, isolated Crossref and OpenAlex export failures from each other, clarified browser-mode resolution errors, and removed tracked generated artifacts.
- 2026-04-26: Simplified downloader and naming internals by removing a dead resolver parameter and an unused metadata-title wrapper, while preserving URL-referer behavior and existing DOI metadata fallback semantics.
- 2026-04-27: Aligned the project into a `src/` layout, moved DOI queues into `data/interim/doi_queues/`, and separated generated metadata and PDF output into `outputs/metadata/` and `outputs/pdfs/`.
- 2026-05-11: Centralized DOI identity, validated existing PDF bytes during resume, extracted config/provider/metadata boundaries, reused browser transport per batch, and added a no-network audit summary.
- 2026-05-11: Added parallel metadata export with ordered CSV writes and a `--max-workers` CLI override for tuning network-bound DOI enrichment.
- 2026-05-11: Added `--request-delay-seconds` metadata pacing to avoid fast initial API bursts followed by throttled long-batch performance.
- 2026-05-11: Made inter-download sleep configurable, rejected config directory paths that collide with files, preserved colliding OpenAlex abstract tokens, and avoided OpenAlex title lookups when Crossref metadata is already complete.
- 2026-05-11: Removed Playwright browser download mode and made stale browser config keys fail fast.
- 2026-05-11: Removed unused provider work-fetch helpers, centralized
  download PDF-byte checks on the naming constants, and hardened URL-derived
  filenames against URL-encoded path separators.
- 2026-05-11: Added an explicit download resume message when every queued DOI
  is skipped because it is already parked in the error ledger.
