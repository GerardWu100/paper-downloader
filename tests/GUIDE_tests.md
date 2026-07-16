# GUIDE_tests

## Purpose

`tests/` contains pytest coverage for the `paper_downloader` package. The
folder has an `__init__.py` package marker so strict linting does not treat it
as an implicit namespace package.

## Test Organization

The current test suite is small, so tests may remain flat when that is clearer.
Use subfolders only when they improve navigation:

- `unit/`: pure function and module-level tests with mocked network calls.
- `integration/`: tests that exercise a larger workflow across modules.
- `data/`: small static fixtures used by tests.

## Rules

- Do not call live publisher, Crossref, or OpenAlex services in normal tests.
- Mock network responses unless a test is explicitly marked as external.
- Keep tests focused on real invariants: queue behavior, path resolution,
  metadata fallback, filename safety, PDF validation, audit counts, and
  command-line routing.
- For metadata export, preserve tests that prove parallel workers can finish
  out of order while the CSV still follows DOI queue order.
- Also keep host-pacing tests deterministic by injecting fake sleep and clock
  functions instead of making real test runs wait.
- Import canonical implementation modules directly. The project intentionally
  does not keep compatibility-only wrapper modules for old import paths.
