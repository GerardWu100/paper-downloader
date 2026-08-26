# paper-downloader

Command-line tool that turns a journal `ISSN` (International Standard Serial
Number) into downloaded PDF articles. It exists so you can collect a
journal's articles in three separate, resumable steps instead of one opaque
scrape.

## What it does

The workflow is:

```text
ISSN -> DOI text file -> metadata CSV -> PDF downloads
```

- **ISSN to DOI file**: queries OpenAlex and Crossref for every article DOI
  (Digital Object Identifier) in a journal, merges and deduplicates them, and
  writes a DOI queue file.
- **DOI file to metadata CSV**: looks up each DOI on Crossref and OpenAlex and
  writes title, abstract, authors, ORCID IDs, affiliations, published date,
  journal, publisher, keywords, and topics to a CSV.
- **DOI file to PDFs**: fetches each DOI from one or more configured base
  URLs over direct HTTP, resolves simple HTML viewer pages into a PDF link
  when needed, validates the PDF bytes, and saves the file with a DOI marker
  in its name.

It does not do publisher logins, institution authentication, or
publisher-specific click automation, and it does not discover PDF base URLs
for you — you provide those. See
[docs/user/project-review.md](docs/user/project-review.md) for a fuller
review of scope and design choices.

## Requirements

- Python 3.13+
- `uv`
- One or more DOI-based PDF base URLs for the publisher(s) you are targeting

Environment variables (set in `.env`, see `.env.example`):

- `PAPER_DOWNLOADER_BASE_URLS`: comma-separated PDF base URLs, e.g.
  `https://onlinelibrary.wiley.com/doi/pdfdirect,https://onlinelibrary.wiley.com/doi/pdf`
- `PAPER_DOWNLOADER_EMAIL`: your contact email, sent to the Crossref and
  OpenAlex polite pools. Unset by default, and the project never fills in a
  placeholder address for you. Setting it gets you faster and more reliable
  provider responses; `paper-fetch-dois` refuses to run without it, because
  Crossref DOI collection requires one.

## Setup

```bash
uv sync
```

## Usage

Single-purpose entrypoints:

```bash
uv run paper-issn-to-doi --issn 1467-9965
uv run paper-export-metadata --dois-file data/interim/doi_queues/1467-9965_dois.txt
uv run paper-download --dois-file data/interim/doi_queues/1467-9965_dois.txt
```

Equivalent top-level subcommands, plus a local `audit` command that checks
the DOI queue and ledgers without calling any API:

```bash
uv run paper-downloader fetch-dois --issn 1467-9965
uv run paper-downloader export-metadata --dois-file data/interim/doi_queues/1467-9965_dois.txt
uv run paper-downloader download --dois-file data/interim/doi_queues/1467-9965_dois.txt
uv run paper-downloader audit --dois-file data/interim/doi_queues/1467-9965_dois.txt
```

Useful flags: `--max-workers` and `--request-delay-seconds` tune metadata
export parallelism; `--base-url` (repeatable) overrides configured PDF base
URLs; `--retry-error-dois` re-attempts DOIs already parked in the error
ledger from a previous run.

## Configuration

`config.toml` holds the runtime defaults:

- `email`: contact address for the Crossref and OpenAlex polite pools, empty
  by default. `PAPER_DOWNLOADER_EMAIL` in `.env` overrides it.
- `crossref_rows`, `timeout_seconds`: Crossref request settings. Crossref
  caps a page at 1000 results, so larger `crossref_rows` values are clamped
  to 1000 rather than truncating the DOI list.
- `doi_file` / `doi_files`: default DOI queue file(s) for `paper-download`
  and `paper-export-metadata`, so you can run them without `--dois-file`
- `inter_download_sleep_seconds`: pause between PDF downloads (default 3s)
- `dois_dir`, `metadata_dir`, `pdfs_dir`: output locations

CLI flags override `config.toml`, and `config.toml` values override
defaults.

## Layout

```text
src/paper_downloader/   CLI, providers (Crossref, OpenAlex), downloader, metadata export, audit
data/interim/doi_queues/  generated DOI queue + success/error ledger files
outputs/metadata/         exported metadata CSVs
outputs/pdfs/<issn>/<year>/  downloaded PDFs
docs/                      design notes and project review
```

See [GUIDE_ROOT.md](GUIDE_ROOT.md) and [GUIDE_OVERVIEW.md](GUIDE_OVERVIEW.md)
for the full architecture and module-by-module reference.

## Output

- `data/interim/doi_queues/<issn>_dois.txt`: the DOI queue (mutable, used for
  resume)
- `data/interim/doi_queues/<issn>_successful.txt` /
  `<issn>_errors.txt`: success and error ledgers
- `outputs/metadata/<issn>_metadata.csv`: exported metadata
- `outputs/pdfs/<issn>/<year>/*.pdf`: downloaded PDFs, named with a DOI
  marker for resume detection
