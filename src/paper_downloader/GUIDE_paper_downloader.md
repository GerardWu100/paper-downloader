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
- `config.py`: TOML loading, `.env` loading, path resolution, base URL parsing,
  inter-download sleep parsing, and boundary validation.
- `models.py`: canonical DOI identity, including list normalization that drops
  blanks and repeats while keeping first-seen order.
- `audit.py`: no-network summary of DOI queue, ledger, and PDF completion state.
- `doi_sources.py`: OpenAlex and Crossref DOI discovery for one journal ISSN.
- `providers/`: Crossref and OpenAlex URL construction, headers, and payload
  parsing. See `providers/GUIDE_providers.md`.
- `metadata/`: metadata extraction and CSV export implementation.
- `downloader.py`: DOI-to-PDF download flow, PDF validation, retries, filename
  inference that strips URL-encoded path separators, and save behavior.
- `_http.py`: the shared JSON fetch function, the package `User-Agent`, the
  default request timeout, and the `JsonObject` type alias.
- `naming.py`: title, year, and DOI-marker filename logic, plus the scan that
  classifies already-saved PDFs as valid or corrupt.
- `progress.py`: DOI queue and success/error ledger handling.

## Boundaries

- This package should not contain generated DOI files, metadata CSV files, PDFs,
  or run logs.
- Configuration defaults live in the root `config.toml`.
- User-facing usage docs live in `README.md` and `docs/user/`.
- Developer reference docs live in `docs/reference/`.

## Conventions

- Shared HTTP constants have exactly one definition, in `_http.py`. Do not
  redeclare the `User-Agent` string or the `JsonObject` alias per module.
- Ledger and queue files are rewritten once per pass, never once per DOI. Both
  rewrites read and write the whole file, so a per-DOI call makes a long run
  quadratic in the file size. `record_batch_outcome` collects DOI values into
  caller-owned sets, and the download loop flushes them at the end of the pass.
- `cli.py` describes each command once in the `CLI_COMMANDS` table. Adding a
  command means adding one entry plus its `_add_*_arguments` and `run_*`
  functions, not a new parser builder and a new dispatch branch.
