# GUIDE_data

## Purpose

`data/` stores reusable working data used by the pipeline.

## Contents

- `interim/doi_queues/`: DOI queue files and adjacent success/error ledgers.
- These files are mutable batch state, not final outputs. The download runtime
  rewrites them as work completes.

## Rules

- Put mutable DOI queues and ledgers here.
- Do not put downloaded PDFs here.
- Do not put final metadata exports here.
- Keep large or private research data out of git unless explicitly approved.
