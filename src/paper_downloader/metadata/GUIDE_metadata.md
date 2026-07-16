# GUIDE_metadata

This folder contains DOI metadata extraction and CSV export code.

- `export.py` builds flat `MetadataRecord` rows, extracts Crossref and OpenAlex
  fields, and writes metadata CSV files.

Metadata export is network-bound. `export.py` uses bounded parallel workers for
DOI enrichment, then buffers completed records until it can write them in the
same order as the input DOI queue. Keep that ordering invariant when changing
parallel export behavior because downstream CSV comparisons rely on stable rows.
The exporter also spaces request starts per provider host to reduce API
throttling during long batches.

Import metadata export code from `paper_downloader.metadata.export`. The
project does not keep compatibility modules for older metadata import paths.
