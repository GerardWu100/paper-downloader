# GUIDE_src

## Purpose

`src/` contains the importable Python implementation code.

The project uses a `src` layout so tests and command-line entrypoints import
the installed package path instead of accidentally importing files from the
repository root.

## Contents

- `paper_downloader/`: the command-line package for DOI discovery, metadata
  export, PDF downloading, queue progress, audit summaries, provider clients,
  configuration, and filename naming. The package now keeps the canonical
  implementation in the main modules instead of routing through internal
  wrapper layers.

## Rules

- Keep implementation code under `src/paper_downloader/`.
- Do not put generated DOI queues, metadata CSV files, PDFs, logs, notebooks,
  or manual notes here.
- Add a subfolder guide when a new meaningful implementation subfolder is
  created.
