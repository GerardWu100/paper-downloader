# Fable Thoughts, 2026-08-31

Everything here is measured against the project's stated goal in `AGENTS.md`:

> Downloads quant papers and their metadata from the URLs listed in .env.

That goal is a *corpus*, not a *tool*: a usable folder of quantitative-finance
papers and a metadata table. The code is only the means. Right now, the tool is
in much better shape than the corpus.

## 1. What the project does today

The code and README are closely aligned. The package uses only the Python
standard library and has four commands:

| Command | What it does |
| --- | --- |
| `fetch-dois` | Resolves the journal from its ISSN (International Standard Serial Number) on OpenAlex; pages through OpenAlex and Crossref works with cursor pagination; merges, normalizes (lowercase and removes `doi.org/` prefixes), deduplicates, sorts, and **overwrites** `data/interim/doi_queues/<issn>_dois.txt`. Requires a contact email. |
| `export-metadata` | Fetches Crossref and OpenAlex data for each DOI (Digital Object Identifier) with 8 workers and 0.1-second per-host pacing. It merges 11 fields, preferring Crossref, and streams one CSV row per DOI in input order. If both providers fail, it still writes a blank row, so the CSV stays aligned with the queue. **Overwrites** the CSV each run. |
| `download` | Builds `<base_url>/<doi>` from the `.env` URL list, tries the URLs in wrapped order from a random starting point, follows HTML viewer pages to PDF links, validates `%PDF-` bytes, names files from the Crossref/OpenAlex title plus a collision-proof `__doi_...` marker, and saves them under `outputs/pdfs/<issn>/<year>/`. It writes through a `.partial_` file, waits 3 seconds between DOIs, retries current-run failures once, and maintains locked success/error ledgers with atomic rewrites. Resume trusts byte-validated PDFs first, then the ledgers. |
| `audit` | Reports local counts: queue size, pending DOIs, ledger sizes, valid and corrupt marked PDFs, and success rows with no matching file. |

For a project this size, the engineering is strong: DOI identity is centralized
and injective in filenames, ledger rewrites are atomic and batched, pagination
guards against repeated cursors, HTTP retries honor `Retry-After`, and roughly
2,900 lines of tests mock every network call.

## 2. The gap between today and the goal

On this machine, as of today:

| Artifact | State |
| --- | --- |
| Code | Complete, tested, and polished. Last touched around early June; idle for about three months. |
| Metadata | Complete for two journals: 1,092 rows for Mathematical Finance (1467-9965) and 2,975 rows for Quantitative Finance (1469-7688). |
| DOI queues | 1467-9965 has 149 DOIs pending out of about 1,092; roughly 943 were consumed at some point. 1469-7688 has 2,969 pending and is essentially untouched. |
| PDFs | **Zero.** `outputs/pdfs/` does not exist here, and neither do success or error ledgers; both are gitignored. |

The first two pipeline stages are complete for two journals. The stage named in
the goal—the papers themselves—has no verifiable output on this machine. The
roughly 943 Mathematical Finance downloads may be on another machine or may
have been deleted. Git cannot tell us: PDFs and ledgers are deliberately
untracked, and the queue file is the only download state it keeps.

Measured against the goal:

- **Built:** discovery, metadata export, a resumable single-journal downloader,
  and local audit counts.
- **Half-built:** the corpus. Two journals are queued; one was partly downloaded
  somewhere, but its location is unconfirmed. The promised `outputs/runs/`
  folder does not exist.
- **Not started:** incremental refresh, coverage reports beyond raw counts, DOI
  filtering, a link between the metadata CSV and downloaded files, and any
  journal beyond these two.

## 3. Recommended next steps

These are ordered by how much they unblock the goal.

**Step 1. Finish downloading the two existing journals and settle where the
corpus lives.** This is the goal; everything else supports it. First determine
whether the roughly 943 Mathematical Finance PDFs exist elsewhere. Then choose
one canonical location for PDFs and ledgers, document it in `AGENTS.md` or
`mynotes.md`, and run `paper-download` to completion for both queues. Check
`audit` afterwards. At 3 seconds per DOI, the roughly 3,100 pending DOIs should
take 3–4 hours unattended. Until this happens, code changes do not advance the
corpus.

**Step 2. Record error reasons in the error ledger.** Today a failed DOI is
logged as `status=download_error`, while the actual message disappears in the
terminal. Later, you will need to distinguish “HTTP 404, paper genuinely
absent” from “HTTP 403 or timeout, worth retrying.” The plumbing already exists:
`record_batch_outcome` accepts a fields dictionary. Do this before the main
download if possible; its ledgers will be the evidence you analyze.

**Step 3. Add incremental refresh to `fetch-dois`.** `write_doi_file` currently
overwrites the queue, which assumes discovery happens once per journal. That
assumption has already failed: the journals have published three months of new
issues. A `--refresh` mode should fetch the current DOI set, remove DOIs in the
success ledger, error ledger, or on-disk PDF markers, and append only new ones.

**Step 4. Use the open-access locations already being discarded.** The OpenAlex
payloads used by `export-metadata` include `best_oa_location`, which can contain
a direct, legal open-access PDF URL from a publisher, institutional repository,
or arXiv. The exporter currently drops it. Saving it as a metadata column and
letting the downloader try it before or after the `.env` URLs would make part of
the corpus independent of the hidden base URLs at almost no extra network cost.
For quant finance, a meaningful share of recent papers have such a location.
This is the cheapest way to reduce dependence on the most fragile input.

**Step 5. Write a coverage report for each journal to `outputs/runs/`.** Extend
`audit` to report DOIs discovered, metadata filled, PDFs on disk, failures by
error type, and counts by publication year. The metadata CSV provides the year
join. A corpus needs a completeness statement—“Quantitative Finance: 96%
downloaded, missing years 2001–2003”—or “done” is just a feeling.

**Step 6. Define the corpus, then add journals.** “Quant papers” currently
means “two journals” by implication. Write the actual target list into
`AGENTS.md`: journals, working-paper series such as arXiv q-fin or SSRN, and
years. The earlier steps can only be sized properly once this list exists.

I would not prioritize publisher adapter hooks or a base-URL diagnostic command
yet, even though `docs/user/project-review.md` suggests them. They improve the
tool. With zero verified PDFs here, corpus work matters more.

## 4. What you may be missing

Several design decisions are already encoded in the project:

- **ISSN is the universe.** Filenames, queues, output folders, and the CLI assume
  journals with ISSNs. Much quant literature lives in working papers (arXiv
  q-fin, SSRN, NBER), which may not have ISSNs or may fit this model poorly. If
  they belong in the corpus, identity needs a second spine such as an arXiv or
  SSRN ID. It is easier to design that now than after the corpus grows.
- **Discovery runs once.** Queue overwriting encodes this assumption, and three
  idle months have already exposed it.
- **The corpus is untracked state.** Gitignored PDFs and ledgers make sense for
  Git, but leave the real goal without a backup plan or a home. A disk failure
  or machine change could lose the library while the repository still looks
  healthy. Choose a location and add a backup now.
- **The CSV is the metadata store.** Four megabytes for 3,000 rows with embedded
  abstracts is fine; 100,000 rows may be awkward. You already run a ClickHouse
  research server. A `papers` table there, or a Parquet file, becomes a natural
  catalog as the journal count grows. Not urgent—just avoid building more tools
  on top of CSVs than necessary.
- **Download-time metadata lookups repeat export work.** The downloader asks
  Crossref/OpenAlex for title and year even when the metadata CSV already has
  them. Two extra API calls per paper are minor at 3,000 papers but wasteful at
  100,000. Reading the CSV first and falling back to the APIs would be cheap when
  it matters.
- **Nothing joins metadata to files.** The DOI marker makes the join easy, but no
  command produces the useful combined view: each paper, its metadata, and its
  PDF path. An audit-style command could add `has_pdf` and `pdf_path` columns.

Two simpler options are easy to miss:

- Before building adapters or diagnostics for difficult publishers, measure how
  much of each journal is available through open-access locations. That may
  shrink the hard part considerably.
- The alphabetically sorted queue downloads in DOI order, not by importance. If
  recent years should come first, sort the queue by `published_date` from the
  metadata CSV with a short preprocessing script; this need not become a
  feature.

## 5. Directions beyond the current plan

Ranked by fit with the goal:

1. **Corpus reliability:** everything in Section 3.
2. **A consumption layer:** after the corpus exists, extract text from the PDFs,
   load it with the metadata into ClickHouse or a search index, and make the
   corpus searchable—for example, “every abstract mentioning covariance
   shrinkage since 2015.” This is beyond the current goal, but it explains why
   the corpus is worth building and why metadata quality matters. Abstracts,
   topics, and ORCID (Open Researcher and Contributor ID) are already captured.
3. **Content verification:** `%PDF-` proves only that a file is a PDF, not that it
   is the right paper. An endpoint could return the wrong paper and the
   downloader would save it under the requested DOI. A `verify` command could
   extract first-page text and fuzzy-match it against the Crossref title. This is
   worth doing before manual spot checks become impractical.
4. **Interesting, but not useful yet:** publisher adapter hooks, browser
   automation, a general scholarly search layer, and topic-based discovery. Wait
   until the two queued journals are downloaded, reported on, and refreshed once.

## 6. What could go wrong

- **The `.env` base URLs are a single point of failure.** The analysis does not
  inspect them, by design. Endpoints can disappear, change URL shapes, throttle,
  or start serving landing pages instead of PDFs. The project would discover
  this only through a wall of `download_error` rows. If they serve paywalled
  content without authorization, there is also legal and ethical risk. The
  durable responses are legitimate access and open-access routing (Step 4).
  Reducing dependence on the hidden URLs should be a first-class objective.
- **Blocking at scale.** Sequential requests every 3 seconds with an honest
  `paper-downloader/0.1.0` User-Agent are polite, but publishers may still rate-
  limit or block bulk fetching. Success rates may vary by endpoint and worsen
  during a run. Error reasons turn that from a mystery into data. Working around
  blocks is not a path to pursue; reducing the need for them is.
- **Silent coverage loss in discovery.** Crossref pagination stops at the first
  short page. A transient provider problem that returns a short successful page
  can end the crawl early, leaving a queue with too few DOIs. The dual-provider
  merge helps, but a report comparing queue size with the journal's provider
  works-count would make the loss visible.
- **The error ledger quietly shrinks the corpus.** A DOI that fails once is
  skipped on later runs unless you remember `--retry-error-dois`. Transient
  blocking can therefore create permanent holes. Retrying errors periodically
  should be standard practice, and the coverage report should show error-ledger
  age.
- **State is split across machines.** Downloads apparently happened elsewhere.
  Because PDFs and ledgers are untracked, running `paper-download` here would
  re-download the 149 pending Mathematical Finance DOIs—harmless—but could also
  create a second, divergent partial corpus. Settle the canonical machine and
  storage location first.
- **The project drifts toward tool polishing.** The history shows three months of
  hardening, refactoring, and testing, but zero papers on disk here. The code is
  already better than it needs to be for two journals. Before each work session,
  ask whether it will produce more papers, better metadata, or a clearer measure
  of coverage. If not, it is probably serving the tool rather than the goal.
