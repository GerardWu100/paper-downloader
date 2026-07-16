# GUIDE_outputs

## Purpose

`outputs/` stores generated artifacts produced by command-line runs.

## Contents

- `metadata/`: exported article metadata CSV files.
- `pdfs/`: downloaded article PDFs.
- `runs/`: future audit reports, diagnostics, and run summaries.
- The `metadata/` and `pdfs/` folders are produced by the main package runtime,
  not by the compatibility wrappers.

## Rules

- Generated outputs should be reproducible from configuration plus DOI queues
  whenever possible.
- Keep large PDFs and private outputs out of git unless explicitly approved.
- Use `outputs/runs/` for future coverage reports and base-URL diagnostics.
