"""Tests for DOI queue and ledger helpers."""

from __future__ import annotations

from pathlib import Path

from paper_downloader import progress


def test_load_dois_from_file_ignores_comments_and_duplicates(tmp_path: Path) -> None:
    """DOI queue files should ignore comments and repeated DOI values."""
    dois_file = tmp_path / "sample_dois.txt"
    dois_file.write_text(
        "10.1/foo\n# comment\n10.2/bar # inline\n10.1/foo\n",
        encoding="utf-8",
    )

    assert progress.load_dois_from_file(dois_file) == ["10.1/foo", "10.2/bar"]


def test_build_batch_progress_files_uses_neighbor_ledgers(tmp_path: Path) -> None:
    """Success and error ledgers should be adjacent to the DOI queue."""
    progress_files = progress.build_batch_progress_files(
        tmp_path / "1467-9965_dois.txt"
    )

    assert progress_files.success_path == tmp_path / "1467-9965_successful.txt"
    assert progress_files.error_path == tmp_path / "1467-9965_errors.txt"


def test_extract_logged_doi_from_line_supports_plain_and_keyed_formats() -> None:
    """Ledger parsing should accept both old and keyed rows."""
    assert progress.extract_logged_doi_from_line("10.1/foo\n") == "10.1/foo"
    assert (
        progress.extract_logged_doi_from_line(
            "doi=10.2/bar | status=download_error | ts=2026-04-08T12:00:00"
        )
        == "10.2/bar"
    )


def test_remove_dois_from_log_removes_matching_ledger_rows(tmp_path: Path) -> None:
    """Ledger cleanup should remove only the DOI values requested."""
    log_path = tmp_path / "1467-9965_errors.txt"
    log_path.write_text(
        "\n".join(
            [
                "doi=10.1/foo | status=download_error | ts=2026-04-08T12:00:00",
                "doi=10.2/bar | status=download_error | ts=2026-04-08T12:00:01",
                "",
            ]
        ),
        encoding="utf-8",
    )

    progress.remove_dois_from_log(log_path, ["10.1/foo"])

    remaining_lines = log_path.read_text(encoding="utf-8").splitlines()
    assert remaining_lines == [
        "doi=10.2/bar | status=download_error | ts=2026-04-08T12:00:01"
    ]


def test_remove_dois_from_source_queue_normalizes_remaining_dois(
    tmp_path: Path,
) -> None:
    """Queue rewrites should keep remaining DOI values in canonical lowercase."""
    source_file = tmp_path / "sample_dois.txt"
    source_file.write_text(
        "10.1111/MAFI.12111\n10.1111/mafi.12108\n",
        encoding="utf-8",
    )

    progress.remove_dois_from_source_queue(source_file, {"10.1111/mafi.12108"})

    assert source_file.read_text(encoding="utf-8") == "10.1111/mafi.12111\n"


def test_reconcile_pending_dois_respects_existing_pdf_and_error_ledgers(
    tmp_path: Path,
) -> None:
    """Resume reconciliation should skip existing PDFs and parked errors."""
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    existing_pdf = pdf_dir / "paper__doi_10.1__foo.pdf"
    existing_pdf.write_bytes(b"%PDF-1.7\n" + (b"0" * 128))

    decisions = progress.reconcile_pending_dois(
        source_dois=["10.1/foo", "10.2/bar", "10.3/baz"],
        successful_logged_dois=[],
        errored_logged_dois=["10.3/baz"],
        output_root_dir=pdf_dir,
        retry_error_dois=False,
    )

    assert decisions.pending_dois == ["10.2/bar"]
    assert decisions.existing_pdf_dois == ["10.1/foo"]
    assert decisions.skipped_error_dois == ["10.3/baz"]


def test_reconcile_pending_dois_retries_stale_success(tmp_path: Path) -> None:
    """A success ledger without a matching PDF should be retried."""
    decisions = progress.reconcile_pending_dois(
        source_dois=[],
        successful_logged_dois=["10.4/qux"],
        errored_logged_dois=[],
        output_root_dir=tmp_path / "pdfs",
        retry_error_dois=False,
    )

    assert decisions.pending_dois == ["10.4/qux"]
    assert decisions.stale_success_dois == ["10.4/qux"]


def test_reconcile_pending_dois_does_not_trust_corrupt_existing_pdf(
    tmp_path: Path,
) -> None:
    """A DOI marker only counts as complete when the PDF bytes are valid."""
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    corrupt_pdf = pdf_dir / "paper__doi_10.1__foo.pdf"
    corrupt_pdf.write_bytes(b"<html>publisher error page</html>")

    decisions = progress.reconcile_pending_dois(
        source_dois=["10.1/foo"],
        successful_logged_dois=[],
        errored_logged_dois=[],
        output_root_dir=pdf_dir,
        retry_error_dois=False,
    )

    assert decisions.pending_dois == ["10.1/foo"]
    assert decisions.existing_pdf_dois == []
