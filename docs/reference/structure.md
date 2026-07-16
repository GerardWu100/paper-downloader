# Project Structure Reference

This document explains where files belong in `paper-downloader`.

## Pipeline Folders

The project pipeline is:

```text
ISSN -> DOI queue -> metadata CSV -> PDF downloads
```

`ISSN` means International Standard Serial Number. It identifies a journal.
`DOI` means Digital Object Identifier. It identifies an article or other
scholarly work.

The folder mapping is:

| Pipeline stage | Folder | Meaning |
| --- | --- | --- |
| Implementation code | `src/paper_downloader/` | Python package and command-line implementation |
| DOI queue and ledgers | `data/interim/doi_queues/` | Mutable working files used to resume batches |
| Metadata exports | `outputs/metadata/` | Generated CSV files for article screening |
| PDF downloads | `outputs/pdfs/` | Generated downloaded PDF files |
| Run reports | `outputs/runs/` | Future diagnostics, audit reports, and run summaries |

The `paper-downloader audit` command currently prints a local plain-text audit
summary instead of writing into `outputs/runs/`.

## Root Files

- `README.md`: user-facing overview and quick start.
- `config.toml`: default runtime settings.
- `pyproject.toml`: package metadata, dependencies, scripts, pytest settings,
  and setuptools configuration.
- `GUIDE_ROOT.md`: root-level developer guide.
- `GUIDE_OVERVIEW.md`: high-level architecture and data-flow guide.

## Generated Artifacts

Generated PDFs and large outputs should normally stay out of git. Small sample
DOI queues or metadata files may be tracked only when they are intentionally
kept as examples.
