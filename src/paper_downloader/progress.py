"""DOI queue, ledger, and resume helpers.

The downloader treats the DOI file as a mutable queue. Each completed DOI is
removed from the queue and appended to either a success ledger or an error
ledger. Existing PDFs, identified by DOI markers in filenames, are also treated
as already-complete work during resume reconciliation.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from itertools import chain
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

from .models import normalize_doi, normalize_dois_preserving_order
from .naming import collect_completed_doi_suffixes, sanitize_doi_for_filename

# Queue files are named `<issn>_dois.txt`; their ledgers reuse the same stem
# with a different suffix. One list keeps that convention in a single place.
QUEUE_FILE_STEM_SUFFIXES: tuple[str, ...] = ("_dois", "_successful", "_errors")

# Suffix for the sibling file that ledger rewrites are staged in before the
# atomic rename onto the real path.
LEDGER_TEMP_FILE_SUFFIX: str = ".tmp"


@dataclass(frozen=True)
class BatchProgressFiles:
    """Track the queue file and its adjacent progress ledgers."""

    source_path: Path
    success_path: Path
    error_path: Path


@dataclass(frozen=True)
class ResumeDecisions:
    """Store the DOI decisions made before a batch resumes."""

    pending_dois: list[str]
    existing_pdf_dois: list[str]
    skipped_error_dois: list[str]
    stale_success_dois: list[str]


def strip_queue_file_suffix(dois_file_path: Path) -> str:
    """Return the queue-file stem without its `_dois`/`_successful`/`_errors` tail."""
    stem = dois_file_path.stem

    for known_suffix in QUEUE_FILE_STEM_SUFFIXES:
        if stem.endswith(known_suffix):
            return stem.removesuffix(known_suffix)

    return stem


def _rewrite_locked_text_file(
    file_path: Path,
    transform_line: Callable[[str], str | None],
) -> None:
    """Rewrite one text file atomically while holding an exclusive lock.

    The new contents are written to a sibling temporary file, flushed to disk,
    and then renamed over the original. A crash therefore leaves either the old
    ledger or the new one, never a half-truncated file, which matters because
    these ledgers are the only record of which DOIs are already done.

    Parameters
    ----------
    file_path:
        Existing text file to rewrite.
    transform_line:
        Called with each raw line, including its newline. Returns the
        replacement line, or ``None`` to drop the line.
    """
    temp_path = file_path.with_name(f"{file_path.name}{LEDGER_TEMP_FILE_SUFFIX}")

    # The lock is held on the original file for the whole read-and-replace, so
    # a second process cannot interleave its own rewrite of the same ledger.
    with file_path.open("r", encoding="utf-8") as file_handle:
        if fcntl is not None:
            fcntl.flock(file_handle.fileno(), fcntl.LOCK_EX)

        try:
            remaining_lines: list[str] = []

            for raw_line in file_handle.readlines():
                transformed_line = transform_line(raw_line)

                if transformed_line is None:
                    continue

                remaining_lines.append(transformed_line)

            with temp_path.open("w", encoding="utf-8") as temp_handle:
                temp_handle.write("".join(remaining_lines))
                temp_handle.flush()
                os.fsync(temp_handle.fileno())

            os.replace(temp_path, file_path)
        finally:
            temp_path.unlink(missing_ok=True)

            if fcntl is not None:
                fcntl.flock(file_handle.fileno(), fcntl.LOCK_UN)


def load_dois_from_file(dois_file_path: Path) -> list[str]:
    """Load DOI values from a text queue file.

    Blank lines are ignored. Inline comments beginning with `#` are stripped.
    """
    if not dois_file_path.exists():
        raise FileNotFoundError(f"DOI file not found: {dois_file_path}")

    if not dois_file_path.is_file():
        raise ValueError(f"DOI file path is not a file: {dois_file_path}")

    loaded_dois: list[str] = []

    with dois_file_path.open("r", encoding="utf-8") as dois_file:
        for raw_line in dois_file:
            content_without_comment = raw_line.split("#", maxsplit=1)[0]
            normalized_content = content_without_comment.strip()

            if not normalized_content:
                continue

            loaded_dois.append(normalized_content)

    return normalize_dois_preserving_order(loaded_dois)


def build_batch_progress_files(dois_file_path: Path) -> BatchProgressFiles:
    """Return the queue and ledger paths associated with one DOI batch file."""
    base_stem = strip_queue_file_suffix(dois_file_path)
    success_path = dois_file_path.with_name(f"{base_stem}_successful.txt")
    error_path = dois_file_path.with_name(f"{base_stem}_errors.txt")

    return BatchProgressFiles(
        source_path=dois_file_path,
        success_path=success_path,
        error_path=error_path,
    )


def extract_logged_doi_from_line(line: str) -> str | None:
    """Extract the DOI value from one ledger line."""
    stripped_line = line.strip()

    if stripped_line and "|" not in stripped_line and not stripped_line.startswith("#"):
        return normalize_doi(stripped_line)

    for raw_field in line.split("|"):
        normalized_field = raw_field.strip()

        if not normalized_field.startswith("doi="):
            continue

        return normalize_doi(normalized_field.removeprefix("doi="))

    return None


def load_logged_doi_list(log_path: Path) -> list[str]:
    """Load DOI values from one ledger, preserving file order."""
    if not log_path.exists():
        return []

    logged_dois: list[str] = []
    seen_dois: set[str] = set()

    with log_path.open("r", encoding="utf-8") as log_file:
        for raw_line in log_file:
            logged_doi = extract_logged_doi_from_line(raw_line)

            if logged_doi is None:
                continue

            if logged_doi in seen_dois:
                continue

            seen_dois.add(logged_doi)
            logged_dois.append(logged_doi)

    return logged_dois


def _format_progress_line(doi: str, fields: dict[str, str] | None) -> str:
    """Format one ledger line for a DOI, with or without trailing fields."""
    normalized_doi = normalize_doi(doi)

    if fields is None:
        return f"{normalized_doi}\n"

    parts = [f"doi={normalized_doi}"]

    for key, value in fields.items():
        parts.append(f"{key}={value}")

    return " | ".join(parts) + "\n"


def _append_locked_lines(log_path: Path, lines: list[str]) -> None:
    """Append lines to a ledger in one locked write."""
    if not lines:
        return

    log_path.parent.mkdir(parents=True, exist_ok=True)

    with log_path.open("a", encoding="utf-8") as log_file:
        if fcntl is not None:
            fcntl.flock(log_file.fileno(), fcntl.LOCK_EX)

        try:
            log_file.write("".join(lines))
        finally:
            if fcntl is not None:
                fcntl.flock(log_file.fileno(), fcntl.LOCK_UN)


def append_progress_entry(
    log_path: Path,
    doi: str,
    fields: dict[str, str] | None = None,
) -> None:
    """Append one DOI record to a ledger file."""
    _append_locked_lines(log_path, [_format_progress_line(doi, fields)])


def append_progress_entries(
    log_path: Path,
    dois: list[str],
    fields: dict[str, str] | None = None,
) -> None:
    """Append many DOI records that share one field set, in a single write.

    Resume can classify an entire existing PDF library at once, so opening,
    locking, and closing the ledger per DOI would dominate that phase. All the
    lines are built first and written under one lock.

    Parameters
    ----------
    log_path:
        Ledger path to append to.
    dois:
        DOI values to record, in the order they should appear.
    fields:
        Fields shared by every appended row, such as
        ``{"status": "existing_pdf"}``. ``None`` writes bare DOI lines.
    """
    _append_locked_lines(
        log_path,
        [_format_progress_line(doi, fields) for doi in dois],
    )


def remove_dois_from_log(
    log_path: Path,
    dois: set[str] | list[str] | tuple[str, ...],
) -> None:
    """Remove one or more DOI values from a ledger file.

    Parameters
    ----------
    log_path:
        Ledger path such as ``*_errors.txt`` or ``*_successful.txt``.
    dois:
        DOI values to remove from the ledger. Blank DOI values are ignored.
    """
    dois_to_remove = set(normalize_dois_preserving_order(dois))

    if not dois_to_remove:
        return

    if not log_path.exists():
        return

    def keep_line(raw_line: str) -> str | None:
        logged_doi = extract_logged_doi_from_line(raw_line)

        if logged_doi in dois_to_remove:
            return None

        return raw_line

    _rewrite_locked_text_file(log_path, keep_line)


def remove_dois_from_source_queue(
    source_path: Path,
    dois: set[str] | list[str] | tuple[str, ...],
) -> None:
    """Remove settled DOI values from the mutable queue file."""
    dois_to_remove = set(normalize_dois_preserving_order(dois))

    if not dois_to_remove:
        return

    def rewrite_queue_line(raw_line: str) -> str | None:
        content_without_comment, comment_separator, comment_text = raw_line.partition(
            "#"
        )
        normalized_doi = normalize_doi(content_without_comment)

        if normalized_doi in dois_to_remove:
            return None

        if not normalized_doi:
            return raw_line

        # Queue files are mutable state. When we rewrite after a completed
        # batch, keep the remaining DOI identities in the same canonical form
        # used by ledger parsing and resume checks.
        if comment_separator:
            return f"{normalized_doi} #{comment_text}"

        return f"{normalized_doi}\n"

    _rewrite_locked_text_file(source_path, rewrite_queue_line)


def record_batch_outcome(
    progress_files: BatchProgressFiles | None,
    successful_dois: set[str],
    errored_dois: set[str],
    doi: str,
    status: str,
    resolved_error_dois: set[str],
    pdf_path: Path | None = None,
) -> None:
    """Record one DOI outcome in the appropriate ledger.

    Both file rewrites this function could trigger are deferred to one call at
    the end of the pass: queue removal happens in the download loop, and error
    rows for DOIs that later succeeded are collected in ``resolved_error_dois``
    for the caller to clear in a single pass. Rewriting either file per DOI
    would cost one full read-and-write of the whole file per DOI.

    Parameters
    ----------
    progress_files:
        Queue and ledger paths, or ``None`` when the batch is not resumable.
    successful_dois:
        Mutable set of DOI values already written to the success ledger.
    errored_dois:
        Mutable set of DOI values currently in the error ledger.
    doi:
        DOI whose outcome is being recorded.
    status:
        ``"success"`` or an error status such as ``"download_error"``.
    resolved_error_dois:
        Mutable set this function adds to when a DOI succeeds after previously
        failing. The caller passes it to :func:`remove_dois_from_log` once.
    pdf_path:
        Saved PDF path recorded alongside a success row.
    """
    if progress_files is None:
        return

    doi = normalize_doi(doi)
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    if status == "success":
        # A DOI that succeeds on a later retry should no longer remain in the
        # error ledger. Keep the ledger aligned with the final outcome.
        if doi in errored_dois:
            resolved_error_dois.add(doi)
            errored_dois.discard(doi)

        if doi in successful_dois:
            return

        fields = {"status": status, "ts": timestamp}

        if pdf_path is not None:
            fields["pdf"] = pdf_path.name

        append_progress_entry(progress_files.success_path, doi, fields)
        successful_dois.add(doi)
        return

    if doi in errored_dois:
        return

    append_progress_entry(
        progress_files.error_path,
        doi,
        {"status": status, "ts": timestamp},
    )
    errored_dois.add(doi)


def derive_issn_from_dois_file(dois_file_path: Path) -> str | None:
    """Derive an ISSN from a queue file named `<issn>_dois.txt`."""
    stem = dois_file_path.stem

    if stem.endswith("_dois"):
        return stem.removesuffix("_dois")

    return None


def reconcile_pending_dois(
    source_dois: list[str],
    successful_logged_dois: list[str],
    errored_logged_dois: list[str],
    output_root_dir: Path,
    retry_error_dois: bool,
) -> ResumeDecisions:
    """Reconcile queue, ledgers, and existing PDFs into one pending worklist."""
    completed_doi_suffixes = collect_completed_doi_suffixes(output_root_dir)
    successful_logged_set = {normalize_doi(doi) for doi in successful_logged_dois}
    errored_logged_set = {normalize_doi(doi) for doi in errored_logged_dois}

    # The queue leads, because its order is the order the operator asked for.
    # Ledger DOIs follow so a queue file trimmed mid-run still reconciles.
    candidate_dois = normalize_dois_preserving_order(
        chain(source_dois, successful_logged_dois, errored_logged_dois)
    )

    pending_dois: list[str] = []
    existing_pdf_dois: list[str] = []
    skipped_error_dois: list[str] = []
    stale_success_dois: list[str] = []

    for doi in candidate_dois:
        doi_resume_suffix = sanitize_doi_for_filename(doi)

        if doi_resume_suffix in completed_doi_suffixes:
            existing_pdf_dois.append(doi)
            continue

        if doi in successful_logged_set:
            stale_success_dois.append(doi)
            pending_dois.append(doi)
            continue

        if doi in errored_logged_set and not retry_error_dois:
            skipped_error_dois.append(doi)
            continue

        pending_dois.append(doi)

    return ResumeDecisions(
        pending_dois=pending_dois,
        existing_pdf_dois=existing_pdf_dois,
        skipped_error_dois=skipped_error_dois,
        stale_success_dois=stale_success_dois,
    )
