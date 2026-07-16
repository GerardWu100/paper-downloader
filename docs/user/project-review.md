# Project Review For Users

`paper-downloader` is a command-line tool for building a journal article pipeline from one `ISSN` (International Standard Serial Number).

The workflow is simple on the surface:

```text
ISSN
  -> DOI list
  -> metadata CSV
  -> PDF files
```

Underneath, the project makes a few deliberate design choices that are worth understanding before you rely on it.

## Who This Project Is For

This project fits you if:

- you already know the journal `ISSN`
- you already know one or more publisher DOI-based PDF endpoints
- you want a resumable batch workflow instead of a one-off script
- you care about keeping an inspectable DOI worklist between discovery and download

This project is not a full scholarly search engine. It does not discover journals for you, guess publisher download URLs for you, or automate licensed login flows.

## Feature Summary

The current feature set is stronger than the package size suggests.

| Feature | What it does | Why it matters |
| --- | --- | --- |
| ISSN to DOI collection | Queries OpenAlex and Crossref for journal article `DOI` values | Avoids depending on only one metadata source |
| DOI normalization | Strips DOI URL prefixes, deduplicates, and sorts DOI values | Produces stable queue files that are easy to inspect and diff |
| Metadata export | Builds one `CSV` (Comma-Separated Values) row per DOI | Lets you screen papers before downloading PDFs |
| PDF download by DOI pattern | Tries one or more configured `base_url/<doi>` patterns | Keeps the downloader generic across publishers that share DOI-based URLs |
| HTML viewer resolution | Detects HTML landing pages and searches them for likely PDF targets | Handles a common publisher pattern without custom adapters |
| Resume support | Uses a mutable queue file plus success and error ledgers | Makes large download batches operationally safer |
| DOI marker in filenames | Appends a DOI marker like `__doi_10.1111__mafi.12108` | Lets the tool detect already-downloaded papers even if ledgers drift |
| Multi-queue batch mode | Reads `doi_file` or `doi_files` from `config.toml` | Supports unattended runs across multiple journals |
| Retry behavior | Retries current-run failures once automatically | Improves recovery from transient upstream failures |
| Title-and-year naming | Uses Crossref first and OpenAlex second for readable filenames and year folders | Produces output that is easier to browse manually |
| Generated artifact hygiene | Ignores saved PDFs and success/error ledgers in Git | Keeps the repository focused on source code and reusable inputs |

## Main Design Choices

### 1. Split the workflow into three artifacts

The project does not go straight from `ISSN` to PDF. It stops at:

1. a DOI queue file
2. a metadata CSV
3. a PDF folder

That is a strong choice.

It means the DOI list becomes a reusable intermediate dataset. You can inspect coverage, export metadata without downloading anything, hand-edit the queue, or resume a broken batch without rerunning journal discovery.

For research work, this is usually better than an opaque one-shot downloader.

### 2. Use two metadata providers, not one

The DOI discovery and metadata layers both combine Crossref and OpenAlex.

That matters because neither source is complete in every case:

- Crossref often has better publisher-style bibliographic metadata
- OpenAlex often helps fill missing fields such as abstract fragments, topics, or fallback publication year

The code uses Crossref first for several fields, then falls back to OpenAlex when needed. That is a pragmatic choice rather than a theoretical one.

### 3. Keep the downloader generic

The downloader assumes the publisher can be reached through one or more DOI-based URL templates:

```text
<base_url>/<doi>
```

This is intentionally narrow. It avoids building a large adapter system too early.

The upside is simplicity. The downside is that publishers with complex click paths, tokenized links, or authentication walls will not work well without further development.

### 4. Prefer direct HTTP and avoid browser automation

Direct HTTP is the only transport because it is lighter, faster, and easier to
debug. The downloader can still inspect simple HTML pages for PDF links, but it
does not launch a local browser or try to simulate a user session.

### 5. Treat progress files as part of the system

Many small downloaders log loosely. This one goes further:

- the DOI queue is mutable
- successes are recorded in `*_successful.txt`
- failures are recorded in `*_errors.txt`
- the downloader can skip previously failed DOI values unless you explicitly retry them

That is an operational design choice. It treats downloading as a batch process that may be interrupted and resumed, not as a single clean run.

### 6. Use DOI markers in filenames

A saved PDF filename includes a DOI marker. That means the downloader can infer completion from the filesystem itself, not only from the ledgers.

This is a good defensive design choice because ledgers can go stale, but a valid saved PDF is the thing you actually care about.

### 7. Keep throttling simple

The current implementation sleeps between DOI downloads. The default is 3
seconds, and `inter_download_sleep_seconds` in `config.toml` can tune it.

That is a blunt tool, but a reasonable default for a small project. It is easier to reason about than adaptive rate limiting and less likely to create accidental burstiness.

## What Users Should Know Before Using It

The project is useful, but its scope is narrower than “download any academic PDF.”

| Area | Current behavior | Practical implication |
| --- | --- | --- |
| Journal discovery | Requires a known ISSN | Good for targeted journal collection, not topic search |
| PDF endpoint discovery | Requires known base URLs | Users still need some publisher-specific setup knowledge |
| Authentication | Not implemented | Paywalled or institution-gated flows usually will not work yet |
| Browser automation | Not implemented | Rendered, login-gated, or click-driven flows need separate tooling |
| Metadata export | Flat CSV schema | Good for screening, limited for richer bibliometric analysis |
| Retry logic | One automatic retry for current-run failures | Helps with transient issues, not persistent publisher-specific blockers |
| Generated outputs | PDFs and success/error ledgers are ignored by Git | Local runs do not clutter commits with downloaded files or run ledgers |

## Best Next Features

These are the features I would prioritize if the goal is to make the project more useful in practice without bloating it too early.

### 1. Coverage diagnostics and download audit reports

Add a report that summarizes:

- DOI count discovered per journal
- metadata export success rate
- PDF download success rate
- failures by error type
- success and failure counts by publication year

Why this matters:

Right now the project can do the work, but it does not yet help the user judge the quality of the result set. For research workflows, that audit layer is often as important as the downloader itself.

### 2. DOI filtering before export or download

Add filters such as:

- publication year range
- article type
- keyword match in title
- keep or exclude already-downloaded DOI values

Why this matters:

A full journal history can be much larger than you actually want. Filtering the DOI queue would make the intermediate artifact more valuable and reduce wasted download attempts.

### 3. A “diagnose this base URL” command

Add a command that tests a small DOI sample against each configured base URL and reports:

- which transport worked
- whether the server returned HTML or PDF
- which candidate PDF links were discovered from the HTML page
- which errors look transient versus structural

Why this matters:

The hardest part for a user is often not running the batch. It is figuring out whether the chosen publisher URL pattern is valid. A diagnostic command would reduce trial and error.

### 4. Publisher adapter hooks

Keep the current generic downloader, but allow optional publisher-specific adapters for stubborn sites.

Why this matters:

This is the cleanest path to broader coverage. The generic path stays simple, and only the difficult publishers need custom logic.

### 5. Incremental journal updates

Add a mode that refreshes an existing ISSN queue by appending only newly discovered DOI values since the last run.

Why this matters:

For ongoing monitoring, users usually do not want to rebuild the whole journal queue every time.

## Suggested Feature Order

If you want a practical roadmap, this order makes the most sense:

1. Coverage diagnostics and audit reports
2. DOI filtering and queue management
3. Base-URL diagnostic command
4. Incremental journal updates
5. Publisher adapter hooks

That order gives the most user value before the codebase takes on the complexity of authentication and publisher-specific automation.

## Bottom Line

`paper-downloader` is best understood as a small, opinionated journal-ingestion pipeline, not just a PDF downloader.

Its strongest ideas are:

- a reusable DOI queue as the center of the workflow
- dual-source metadata collection through Crossref and OpenAlex
- resumable batch downloads with explicit ledgers
- a generic downloader that can stay simple until real publisher-specific complexity is justified

Those are sensible choices. The biggest missing layer is not raw downloading power. It is better operator feedback: diagnostics, filtering, coverage reporting, and clearer support for publisher-specific cases.
