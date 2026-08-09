"""DOI queue, ledger, and resume helpers.

The downloader treats the DOI file as a mutable queue. Each completed DOI is
removed from the queue and appended to either a success ledger or an error
ledger. Existing PDFs, identified by DOI markers in filenames, are also treated
as already-complete work during resume reconciliation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

from .models import normalize_doi
from .naming import collect_completed_doi_suffixes, sanitize_doi_for_filename


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


def normalize_dois(dois: list[str]) -> list[str]:
    """Normalize a DOI list while preserving first-seen order."""
    normalized_dois: list[str] = []
    seen_dois: set[str] = set()

    for raw_doi in dois:
        normalized_doi = normalize_doi(raw_doi)

        if not normalized_doi:
            continue

        if normalized_doi in seen_dois:
            continue

        seen_dois.add(normalized_doi)
        normalized_dois.append(normalized_doi)

    return normalized_dois


def _normalized_doi_set(dois: set[str] | list[str] | tuple[str, ...]) -> set[str]:
    """Normalize a DOI collection into the rewrite comparison set."""
    normalized_dois: set[str] = set()

    for doi in dois:
        normalized_doi = normalize_doi(doi)

        if normalized_doi:
            normalized_dois.add(normalized_doi)

    return normalized_dois


def _rewrite_locked_text_file(
    file_path: Path,
    transform_line: Callable[[str], str | None],
) -> None:
    """Rewrite one text file in place while holding an exclusive lock."""
    with file_path.open("r+", encoding="utf-8") as file_handle:
        if fcntl is not None:
            fcntl.flock(file_handle.fileno(), fcntl.LOCK_EX)

        try:
            remaining_lines: list[str] = []

            for raw_line in file_handle.readlines():
                transformed_line = transform_line(raw_line)

                if transformed_line is None:
                    continue

                remaining_lines.append(transformed_line)

            file_handle.seek(0)
            file_handle.truncate()
            file_handle.write("".join(remaining_lines))
        finally:
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

    return normalize_dois(loaded_dois)


def build_batch_progress_files(dois_file_path: Path) -> BatchProgressFiles:
    """Return the queue and ledger paths associated with one DOI batch file."""
    stem = dois_file_path.stem
    base_stem = stem

    for known_suffix in ("_dois", "_successful", "_errors"):
        if base_stem.endswith(known_suffix):
            base_stem = base_stem.removesuffix(known_suffix)
            break

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


def append_progress_entry(
    log_path: Path,
    doi: str,
    fields: dict[str, str] | None = None,
) -> None:
    """Append one DOI record to a ledger file."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_doi = normalize_doi(doi)

    with log_path.open("a", encoding="utf-8") as log_file:
        if fcntl is not None:
            fcntl.flock(log_file.fileno(), fcntl.LOCK_EX)

        try:
            if fields is None:
                log_file.write(f"{normalized_doi}\n")
                return

            parts = [f"doi={normalized_doi}"]

            for key, value in fields.items():
                parts.append(f"{key}={value}")

            log_file.write(" | ".join(parts) + "\n")
        finally:
            if fcntl is not None:
                fcntl.flock(log_file.fileno(), fcntl.LOCK_UN)


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
    dois_to_remove = _normalized_doi_set(dois)

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
    dois_to_remove = _normalized_doi_set(dois)

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
    pdf_path: Path | None = None,
) -> None:
    """Record one DOI outcome in the appropriate ledger.

    Queue removal is deferred to a single batch call in the download loop
    so the queue file is rewritten once per batch rather than once per DOI.
    """
    if progress_files is None:
        return

    doi = normalize_doi(doi)
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    if status == "success":
        # A DOI that succeeds on a later retry should no longer remain in the
        # error ledger. Keep the ledger aligned with the final outcome.
        if doi in errored_dois:
            remove_dois_from_log(progress_files.error_path, [doi])
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

    candidate_dois: list[str] = []
    seen_candidate_dois: set[str] = set()

    for doi_group in (
        source_dois,
        successful_logged_dois,
        errored_logged_dois,
    ):
        for raw_doi in doi_group:
            normalized_doi = normalize_doi(raw_doi)

            if not normalized_doi:
                continue

            if normalized_doi in seen_candidate_dois:
                continue

            seen_candidate_dois.add(normalized_doi)
            candidate_dois.append(normalized_doi)

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
