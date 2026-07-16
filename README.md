# paper-downloader

`paper-downloader` is a small command-line tool for journal article collection.
It is built around three jobs:

1. Given an `ISSN` (International Standard Serial Number), collect all article
   `DOI` values (Digital Object Identifier) and save them to a text file.
2. Given a DOI text file, fetch article metadata and export it to a CSV file.
3. Given a DOI text file, download PDF files for those articles.

The project is for users who already know one journal `ISSN` and have access to
one or more publisher PDF endpoint patterns such as
`https://publisher.example/pdf/<doi>`.

Downloads use direct HTTP and can resolve simple HTML viewer pages into PDF
targets when those pages expose likely PDF links.

## What This Project Does

The workflow is intentionally split into separate steps:

```text
ISSN
  -> DOI text file
  -> metadata CSV
  -> PDF downloads
```

That separation is useful because the DOI list becomes a reusable intermediate
artifact:

- You can inspect it before downloading anything.
- You can export metadata without downloading PDFs.
- You can resume partial download batches safely.

## Current Scope

This repository currently supports:

- `ISSN -> DOI text file` using OpenAlex and Crossref.
- `DOI text file -> metadata CSV` using Crossref and OpenAlex.
- `DOI text file -> PDFs` using one or more configured DOI-based PDF URLs.
- Resume support using a mutable DOI queue plus success and error ledgers.

This repository does not currently support:

- publisher login flows
- institution authentication flows
- publisher-specific click automation
- discovery of PDF base URLs for you

For a concise user-facing review of the current feature set, design choices,
limitations, and recommended next features, see
[docs/user/project-review.md](docs/user/project-review.md).

## Installation

This project uses `uv` for Python execution and dependency management.

Requirements:

- Python `3.11` or newer
- `uv`

Install dependencies:

```bash
uv sync
```

## Configuration

There are two configuration files at the project root:

- `.env`
- `config.toml`

### `.env`

Use `.env` for one or more DOI download base URLs:

```bash
PAPER_DOWNLOADER_BASE_URLS=https://onlinelibrary.wiley.com/doi/pdfdirect,https://onlinelibrary.wiley.com/doi/pdf,https://onlinelibrary.wiley.com/doi/epdf
```

The loader normalizes each entry before use. That means these all resolve to a
usable base URL:

- `publisher.example/pdf`
- `www.publisher.example/pdf/`
- `https://publisher.example/pdf/`

For each DOI `d`, the downloader builds:

```text
<base_url>/<d>
```

When multiple base URLs are configured, the downloader chooses one random base
URL as the first attempt for that DOI. If that first URL fails or returns HTML
instead of a real PDF, the downloader exhausts the rest of the configured URL
list in wrapped order before recording the DOI as a failure.

You can also set the Crossref polite-pool email in `.env`:

```bash
PAPER_DOWNLOADER_EMAIL=your_email@example.com
```

### `config.toml`

Important settings in `config.toml`:

- `email`: Crossref contact email when `.env` does not override it
- `doi_file`: one default DOI queue file for `paper-download`
- `doi_files`: a list of DOI queue files for unattended multi-journal downloads or metadata exports
- `timeout_seconds`: HTTP timeout for metadata and PDF requests
- `inter_download_sleep_seconds`: seconds to pause between DOI downloads
- `dois_dir`: working folder for DOI text files and ledger files
- `metadata_dir`: output folder for metadata CSV files
- `pdfs_dir`: output folder for downloaded PDFs

`crossref_rows` and `timeout_seconds` must be positive.
`inter_download_sleep_seconds` must be non-negative. `doi_file` and every
`doi_files` entry must be strings. Configured output directory settings must
not point to existing files. Removed browser settings such as `use_browser`,
`browser_headless`, and `browser_executable_path` are rejected so stale config
does not imply unsupported behavior.

The downloader sleeps between DOI downloads according to
`inter_download_sleep_seconds`, which defaults to 3 seconds.

For download automation, `config.toml` can hold either one DOI queue file:

```toml
doi_file = "data/interim/doi_queues/1467-9965_dois.txt"
```

or several DOI queue files:

```toml
doi_files = [
  "data/interim/doi_queues/1467-9965_dois.txt",
  "data/interim/doi_queues/2214-6369_dois.txt",
]
```

When `doi_file` or `doi_files` is set, you can run:

```bash
uv run paper-download
```

The downloader will process those queue files in order. CLI flags still take
priority, so `--doi` overrides everything and `--dois-file` overrides the
config list.

## Quick Start

### 1. Build a DOI text file from an ISSN

Example:

```bash
uv run paper-issn-to-doi --issn 1467-9965
```

Output:

```text
data/interim/doi_queues/1467-9965_dois.txt
```

What happens in this step:

- OpenAlex resolves the journal source from the ISSN.
- OpenAlex work pages are scanned for article DOIs.
- Crossref work pages are scanned for journal-article DOIs.
- DOI values are normalized, deduplicated, sorted, and written to disk.

### 2. Export metadata from the DOI text file

Example:

```bash
uv run paper-export-metadata --dois-file data/interim/doi_queues/1467-9965_dois.txt
```

Output:

```text
outputs/metadata/1467-9965_metadata.csv
```

The exported CSV currently includes:

- DOI
- title
- abstract
- authors
- ORCID IDs
- affiliations
- published date
- journal title
- publisher
- keywords
- topics

During export, the command prints per-DOI progress lines to the terminal so
long metadata batches do not look stalled. Metadata lookup is network-bound, so
the exporter uses 8 parallel workers by default while still writing CSV rows in
the same order as the DOI queue. It also waits 0.05 seconds between request
starts to the same API host, which helps avoid a fast initial burst followed by
provider throttling.

Tune parallelism if a provider throttles requests or if you want a faster run:

```bash
uv run paper-export-metadata \
  --dois-file data/interim/doi_queues/1467-9965_dois.txt \
  --max-workers 16
```

If the run still starts fast and then slows sharply, reduce worker pressure or
increase the per-host delay:

```bash
uv run paper-export-metadata \
  --dois-file data/interim/doi_queues/1467-9965_dois.txt \
  --max-workers 6 \
  --request-delay-seconds 0.15
```

If one provider lookup fails during export, the exporter still tries the other
provider before falling back to blank fields. If a DOI cannot be enriched from
either provider, the CSV still keeps one row for that DOI with blank metadata
fields, and the terminal progress stream logs the per-DOI failure message.

Override the CSV path if you want:

```bash
uv run paper-export-metadata \
  --dois-file data/interim/doi_queues/1467-9965_dois.txt \
  --output-csv outputs/metadata/1467-9965_custom_metadata.csv
```

If `config.toml` already defines `doi_file` or `doi_files`, this is also valid:

```bash
uv run paper-export-metadata
```

When several DOI queue files are configured, the exporter processes them in
order and writes one CSV per queue file into `metadata_dir`.

### 3. Download PDFs from the DOI text file

Example:

```bash
uv run paper-download --dois-file data/interim/doi_queues/1467-9965_dois.txt
```

If `config.toml` already defines `doi_file` or `doi_files`, this is also valid:

```bash
uv run paper-download
```

By default, each batch makes one automatic second pass over the DOI values that
failed during that same queue run. Older DOI values already parked in the
adjacent `data/interim/doi_queues/<ISSN>_errors.txt` ledger stay skipped unless
you pass `--retry-error-dois`.

Typical output location:

```text
outputs/pdfs/1467-9965/<YEAR>/...pdf
```

If article year metadata is unavailable, the file falls back to:

```text
outputs/pdfs/1467-9965/...pdf
```

You can also download one DOI directly:

```bash
uv run paper-download --doi 10.1111/mafi.12108 --base-url https://publisher.example/pdf
```

## Main Commands

There are two equivalent command styles.

### Single-purpose entrypoints

```bash
uv run paper-issn-to-doi --issn 1467-9965
uv run paper-export-metadata --dois-file data/interim/doi_queues/1467-9965_dois.txt
uv run paper-download --dois-file data/interim/doi_queues/1467-9965_dois.txt
```

### Top-level subcommands

```bash
uv run paper-downloader fetch-dois --issn 1467-9965
uv run paper-downloader export-metadata --dois-file data/interim/doi_queues/1467-9965_dois.txt
uv run paper-downloader download --dois-file data/interim/doi_queues/1467-9965_dois.txt
uv run paper-downloader audit --dois-file data/interim/doi_queues/1467-9965_dois.txt
```

The `audit` command is local only. It reads the DOI queue, adjacent success and
error ledgers, and configured PDF folder; it does not call Crossref, OpenAlex,
or any publisher.

## PDF Download Notes

### Override base URLs at run time

Use one base URL:

```bash
uv run paper-download \
  --dois-file data/interim/doi_queues/1467-9965_dois.txt \
  --base-url https://publisher.example/pdf
```

Use multiple base URLs:

```bash
uv run paper-download \
  --dois-file data/interim/doi_queues/1467-9965_dois.txt \
  --base-url https://first.example/pdf \
  --base-url https://second.example/pdf
```

When you pass multiple base URLs, each DOI starts from one random URL from that
list, then falls through the remaining URLs if needed.

### Retry previously failed DOIs

Each failed DOI is recorded in `data/interim/doi_queues/<ISSN>_errors.txt`.

The downloader now behaves in two stages:

1. Process the DOI queue file.
2. Retry the DOI values that failed in that queue once more after the queue is
   exhausted.

If one of those retry attempts succeeds, the downloader removes that DOI row
from `data/interim/doi_queues/<ISSN>_errors.txt` and keeps only the success
ledger entry.

Older DOI values already sitting in `data/interim/doi_queues/<ISSN>_errors.txt`
from previous runs still remain skipped by default. Pass `--retry-error-dois`
when you want to pull those parked error-ledger DOI values back into the
current batch:

```bash
uv run paper-download \
  --dois-file data/interim/doi_queues/1467-9965_dois.txt \
  --retry-error-dois
```

DOI slashes are always preserved in the generated path. For DOI `10.1111/abcd`,
the downloader always requests:

```text
<base_url>/10.1111/abcd
```

## Resume and Progress Tracking

The downloader is designed to resume safely.

It writes and updates these files beside the DOI queue:

- `data/interim/doi_queues/<ISSN>_dois.txt`: mutable DOI queue
- `data/interim/doi_queues/<ISSN>_successful.txt`: DOI values downloaded successfully
- `data/interim/doi_queues/<ISSN>_errors.txt`: DOI values that failed
- `outputs/metadata/<ISSN>_metadata.csv`: metadata export from the DOI queue

Saved PDFs also include a DOI marker in the filename. Example:

```text
Some Article Title__doi_10.1111__mafi.12108.pdf
```

That marker is the main resume signal. If the downloader sees an existing PDF
with the DOI marker and valid PDF bytes, it skips that DOI on later runs. A
zero-byte file or HTML error page renamed to `.pdf` is treated as incomplete.

Failed DOI values in `data/interim/doi_queues/<ISSN>_errors.txt` are also
skipped on later runs by default if they were already parked there before the
current batch started.
Fresh failures from the current queue are retried once automatically after the
queue is exhausted. Pass `--retry-error-dois` when you also want to include the
older parked error-ledger DOI values in the current batch.

## Output Layout

```text
data/interim/doi_queues/
  <ISSN>_dois.txt
  <ISSN>_successful.txt
  <ISSN>_errors.txt

outputs/metadata/
  <ISSN>_metadata.csv

outputs/pdfs/
  <ISSN>/
    <YEAR>/
      *.pdf
```

## How DOI Collection Works

For one ISSN:

1. Query OpenAlex source lookup with `sources/issn:<issn>`.
2. Page through OpenAlex works for that source.
3. Page through Crossref works for the same ISSN.
4. Merge, normalize, deduplicate, and sort DOI values.
5. Write `data/interim/doi_queues/<ISSN>_dois.txt`.

## How Metadata Export Works

For each DOI in the text file:

1. Query Crossref work metadata.
2. Query OpenAlex work metadata.
3. Merge the useful fields into one flat row.
4. If one provider is unavailable, keep metadata from the other provider.
5. Write the final CSV.

Crossref is the main source for several bibliographic fields, while OpenAlex is
also used to reconstruct abstracts and enrich topic metadata when available.

## How PDF Download Works

For each DOI in the text file:

1. Build one or more candidate URLs from the configured base URLs.
2. Request each candidate URL through direct HTTP.
3. If the response is HTML, inspect it for likely embedded PDF targets.
4. If a DOI still fails, append it to `*_errors.txt`.
5. After the queue is exhausted, retry the DOI values that failed in that queue
   once more.
6. If a retry succeeds, remove that DOI row from `*_errors.txt`.
7. Resolve article title and year metadata when metadata providers are available.
8. Save the PDF under a readable filename with a DOI marker.
9. Update the success or error ledger.

Metadata lookup is not required for a PDF save. If Crossref or OpenAlex is
temporarily unavailable after valid PDF bytes have already been fetched, the
downloader saves the PDF with a fallback filename and without a year subfolder.

## Development

Run tests:

```bash
uv run --group dev python -m pytest
```

Run lint checks:

```bash
uv run --group dev python -m ruff check .
```

Useful next steps for this project:

- add publisher-specific adapters when one direct URL pattern is not enough
- add richer metadata export fields if you want screening or research workflows
- add reporting on download coverage by year, DOI, or journal
- use `paper-downloader audit` before and after large batches to spot stale
  success rows, corrupt marked PDFs, and remaining pending DOI values
- add authentication support only if you explicitly need licensed access flows
