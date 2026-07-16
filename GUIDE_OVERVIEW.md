# Overview

## Project tree

```text
paper-downloader/
├── .env
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
├── GUIDE_OVERVIEW.md
├── GUIDE_ROOT.md
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
│       ├── audit.py
│       ├── cli.py
│       ├── config.py
│       ├── doi_sources.py
│       ├── downloader.py
│       ├── metadata/
│       ├── models.py
│       ├── naming.py
│       ├── providers/
│       └── progress.py
├── pyproject.toml
├── README.md
├── tests/
│   ├── GUIDE_tests.md
│   ├── test_cli.py
│   ├── test_doi_sources.py
│   ├── test_downloader.py
│   ├── test_metadata_export.py
│   ├── test_naming.py
│   └── test_progress.py
```

The canonical implementation lives in the main package modules such as
`downloader.py`, `metadata/export.py`, `progress.py`, `config.py`, and
`doi_sources.py`. The project does not keep compatibility-only import modules.

## Purpose

This project downloads article PDFs for one journal ISSN through direct HTTP.
It can inspect simple HTML viewer pages for likely PDF links, but it does not
launch a local browser.

It treats the ISSN as the journal-level identifier, resolves the journal's
article DOIs from OpenAlex and Crossref into a DOI text file, then consumes
that DOI text file either to export article metadata into CSV or to download
PDFs under a configurable base path. The download step can now also consume a
config-defined list of DOI text files in sequence for unattended multi-journal
runs.

## Data flow

For one ISSN, define:

- $I$ as the ISSN
- $D(I)$ as the set of article DOIs returned by OpenAlex and Crossref
- $u(d)$ as the DOI download URL built from DOI $d$
- $f(d)$ as the saved PDF filename with a DOI marker

The system does:

$$
I \rightarrow D(I) \rightarrow \text{doi file} \rightarrow u(d) \rightarrow f(d)
$$

for each DOI $d \in D(I)$.

More concretely:

1. Resolve `OpenAlex source id` from the ISSN.
2. Page through OpenAlex works for that source.
3. Page through Crossref works for the same ISSN.
4. Merge and normalize all DOI values.
 5. Save the DOI queue to `data/interim/doi_queues/<issn>_dois.txt`.
  6. Optionally start a metadata-export step that reads the DOI queue file,
    queries Crossref and OpenAlex per DOI, and writes
    `outputs/metadata/<issn>_metadata.csv`.
7. Start a separate download step that reads one DOI queue file or a configured
   sequence of DOI queue files.
8. For each pending DOI, choose one random starting base URL, then exhaust the
   remaining base URLs in wrapped order.
9. Request `base_url/<doi>` through direct HTTP.
10. If the response is an HTML viewer page, inspect it for
    embedded PDF URLs or download links and retry those HTTP targets.
11. Validate that the final payload is a real PDF. Existing marked PDF files
    must also pass this byte-level check before resume treats them as complete.
12. Resolve title and year metadata from Crossref and OpenAlex when available.
13. Save the file under `outputs/pdfs/<issn>/<year>/` when year is known.
14. If a DOI from the current queue still fails, append it to `*_errors.txt`.
15. After the queue is exhausted, retry those current-queue failures once more.
16. If a retry succeeds, remove that DOI row from `*_errors.txt`.
17. Rewrite the mutable DOI queue and keep the final success/error ledgers.
18. Sleep for the configured inter-download delay before the next DOI so
    requests are not sent back-to-back. The default delay is 3 seconds.

Pagination safety: DOI collection now stops when one provider repeats the same
cursor token, so upstream cursor glitches cannot trap collection in an
infinite loop.

HTML resolver behavior: nested viewer-page resolution now uses the immediate
parent page URL as the HTTP referer on each hop.

Metadata export behavior: Crossref and OpenAlex failures are isolated from each
other. If one provider fails, the exporter keeps useful fields from the other
provider. If both providers fail for one DOI, export continues, writes one blank
fallback row for that DOI, and logs the per-DOI failure line to the progress
stream.

PDF save behavior: title and publication-year metadata improve filenames and
folder placement, but they are optional. Once the downloader has validated PDF
bytes, a metadata outage cannot turn that DOI into a download failure.

## Important assumptions

- The target PDF endpoint should still be expressible as one or more DOI-based
  URLs.
- The default URL builder preserves DOI slashes, because many direct DOI-style
  endpoints expect `base_url/10.xxxx/yyy` instead of percent-encoding the `/`.
- Title-based filenames are preferred over publisher-provided filenames,
  because server names are often generic or unstable.
- Resume relies primarily on DOI markers embedded in saved filenames, not only
  on queue or ledger files.
- The local audit command reports counts for source DOI values, pending DOI
  values, success-ledger DOI values, error-ledger DOI values, valid marked PDFs,
  corrupt marked PDFs, and success rows without matching PDFs. It does this
  without network calls.

## Limitations

- This project does not implement authentication flows.
- This project does not launch a browser or script publisher-specific click
  paths.
- This project assumes one or more DOI download base paths are already known.
- If a server returns a valid PDF with an unexpected non-200 pattern or a
  non-standard redirect chain, the downloader will treat that as a normal HTTP
  fetch result and rely on PDF validation rather than publisher-specific logic.
