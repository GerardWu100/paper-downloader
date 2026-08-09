# GUIDE_metadata

This folder contains DOI metadata extraction and CSV export code.

- `export.py` builds flat `MetadataRecord` rows, extracts Crossref and OpenAlex
  fields, and writes metadata CSV files.

## Author fields

Crossref and OpenAlex nest author data differently: Crossref puts a flat
`author` list on the work, while OpenAlex wraps each contribution in an
`authorships` entry that holds the author object and the institution list side
by side. The three author-derived columns (names, ORCID identifiers,
affiliations) are the same question asked of both shapes.

Each provider therefore gets one adapter that flattens its payload into
`AuthorRow` values, and the three formatters work on those rows regardless of
origin. Add a new author-level column by extending `AuthorRow` and its two
adapters, not by writing a fourth pair of provider-specific extractors.
`build_metadata_record` builds each provider's rows once and reuses them across
all three columns.

Metadata export is network-bound. `export.py` uses bounded parallel workers for
DOI enrichment, then buffers completed records until it can write them in the
same order as the input DOI queue. Keep that ordering invariant when changing
parallel export behavior because downstream CSV comparisons rely on stable rows.
The exporter also spaces request starts per provider host to reduce API
throttling during long batches.

Import metadata export code from `paper_downloader.metadata.export`. The
project does not keep compatibility modules for older metadata import paths.
