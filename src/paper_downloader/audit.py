"""No-network audit summaries for DOI queues and downloaded PDFs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .naming import sanitize_doi_for_filename, scan_marked_pdf_dois
from .progress import (
    build_batch_progress_files,
    load_dois_from_file,
    load_logged_doi_list,
)


@dataclass(frozen=True)
class DownloadAuditSummary:
    """Count local download state for one DOI queue."""

    source_doi_count: int
    pending_doi_count: int
    success_ledger_doi_count: int
    error_ledger_doi_count: int
    existing_valid_pdf_count: int
    corrupt_marked_pdf_count: int
    missing_pdf_after_success_count: int


def build_download_audit_summary(
    dois_file_path: Path,
    pdf_root_dir: Path,
) -> DownloadAuditSummary:
    """Build a local audit summary for one DOI queue without network calls."""
    source_dois = load_dois_from_file(dois_file_path)
    progress_files = build_batch_progress_files(dois_file_path)
    success_ledger_dois = load_logged_doi_list(progress_files.success_path)
    error_ledger_dois = load_logged_doi_list(progress_files.error_path)
    valid_pdf_suffixes, corrupt_pdf_suffixes = scan_marked_pdf_dois(pdf_root_dir)
    source_doi_suffixes = {sanitize_doi_for_filename(doi) for doi in source_dois}
    success_doi_suffixes = {
        sanitize_doi_for_filename(doi) for doi in success_ledger_dois
    }
    pending_doi_suffixes = (
        source_doi_suffixes - valid_pdf_suffixes - success_doi_suffixes
    )
    missing_success_suffixes = success_doi_suffixes - valid_pdf_suffixes

    return DownloadAuditSummary(
        source_doi_count=len(source_dois),
        pending_doi_count=len(pending_doi_suffixes),
        success_ledger_doi_count=len(success_ledger_dois),
        error_ledger_doi_count=len(error_ledger_dois),
        existing_valid_pdf_count=len(valid_pdf_suffixes),
        corrupt_marked_pdf_count=len(corrupt_pdf_suffixes),
        missing_pdf_after_success_count=len(missing_success_suffixes),
    )


def format_download_audit_summary(summary: DownloadAuditSummary) -> str:
    """Format one audit summary as plain terminal text."""
    lines = [
        f"source_dois={summary.source_doi_count}",
        f"pending_dois={summary.pending_doi_count}",
        f"success_ledger_dois={summary.success_ledger_doi_count}",
        f"error_ledger_dois={summary.error_ledger_doi_count}",
        f"existing_valid_pdfs={summary.existing_valid_pdf_count}",
        f"corrupt_marked_pdfs={summary.corrupt_marked_pdf_count}",
        f"missing_pdfs_after_success={summary.missing_pdf_after_success_count}",
    ]
    return "\n".join(lines)
