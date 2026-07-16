"""Tests for no-network download audit summaries."""

from __future__ import annotations

from pathlib import Path

from paper_downloader.audit import build_download_audit_summary
from paper_downloader.progress import build_batch_progress_files


def test_build_download_audit_summary_identifies_completion_gaps(
    tmp_path: Path,
) -> None:
    """Audit should count valid PDFs, corrupt marked PDFs, and stale successes."""
    dois_file = tmp_path / "data" / "interim" / "doi_queues" / "1467-9965_dois.txt"
    dois_file.parent.mkdir(parents=True, exist_ok=True)
    dois_file.write_text("10.1/foo\n10.2/bar\n10.3/baz\n", encoding="utf-8")

    progress_files = build_batch_progress_files(dois_file)
    progress_files.success_path.write_text(
        "\n".join(
            [
                "doi=10.1/foo | status=success | ts=2026-04-08T12:00:00",
                "doi=10.4/missing | status=success | ts=2026-04-08T12:00:01",
                "",
            ]
        ),
        encoding="utf-8",
    )
    progress_files.error_path.write_text(
        "doi=10.3/baz | status=download_error | ts=2026-04-08T12:00:02\n",
        encoding="utf-8",
    )
    pdf_root_dir = tmp_path / "outputs" / "pdfs"
    pdf_root_dir.mkdir(parents=True, exist_ok=True)
    valid_pdf = pdf_root_dir / "paper__doi_10.1__foo.pdf"
    valid_pdf.write_bytes(b"%PDF-1.7\n" + (b"0" * 128))
    corrupt_pdf = pdf_root_dir / "paper__doi_10.2__bar.pdf"
    corrupt_pdf.write_bytes(b"<html>not a pdf</html>")

    summary = build_download_audit_summary(
        dois_file_path=dois_file,
        pdf_root_dir=pdf_root_dir,
    )

    assert summary.source_doi_count == 3
    assert summary.pending_doi_count == 2
    assert summary.success_ledger_doi_count == 2
    assert summary.error_ledger_doi_count == 1
    assert summary.existing_valid_pdf_count == 1
    assert summary.corrupt_marked_pdf_count == 1
    assert summary.missing_pdf_after_success_count == 1
