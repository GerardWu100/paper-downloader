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
- `models.py`: canonical DOI identity normalization.
- `audit.py`: no-network summary of DOI queue, ledger, and PDF completion state.
- `doi_sources.py`: OpenAlex and Crossref DOI discovery for one journal ISSN.
- `providers/`: Crossref and OpenAlex URL construction plus the Crossref
  timed JSON helper used by metadata export.
- `metadata/`: metadata extraction and CSV export implementation.
- `downloader.py`: DOI-to-PDF download flow, PDF validation, retries, filename
  inference that strips URL-encoded path separators, and save behavior.
- `_http.py`: shared HTTP helpers.
- `naming.py`: title, year, and DOI-marker filename logic.
- `progress.py`: DOI queue and success/error ledger handling.

## Boundaries

- This package should not contain generated DOI files, metadata CSV files, PDFs,
  or run logs.
- Configuration defaults live in the root `config.toml`.
- User-facing usage docs live in `README.md` and `docs/user/`.
- Developer reference docs live in `docs/reference/`.
