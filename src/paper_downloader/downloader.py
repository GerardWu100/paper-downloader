"""DOI-to-PDF download runtime.

The module builds one direct PDF URL for each DOI, validates the response,
chooses a readable output filename, resolves simple HTML viewer pages into the
real PDF download URL when possible, and updates the DOI queue and ledgers so
runs can resume safely.
"""

from __future__ import annotations

import random
import re
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from html import unescape
from http.client import IncompleteRead
from pathlib import Path
from typing import TypeAlias
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse
from urllib.request import Request, urlopen

from . import naming
from ._http import DEFAULT_HTTP_USER_AGENT
from .progress import (
    BatchProgressFiles,
    append_progress_entries,
    load_logged_doi_list,
    reconcile_pending_dois,
    record_batch_outcome,
    remove_dois_from_log,
    remove_dois_from_source_queue,
)

CONTENT_DISPOSITION_FILENAME_STAR_PATTERN = re.compile(
    r"filename\*=UTF-8''([^;]+)",
    re.IGNORECASE,
)
CONTENT_DISPOSITION_FILENAME_PATTERN = re.compile(
    r'filename="?([^";]+)"?',
    re.IGNORECASE,
)
HTML_CITATION_PDF_URL_PATTERN = re.compile(
    r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
HTML_IFRAME_EMBED_PATTERN = re.compile(
    r'<(?:iframe|embed)[^>]+src=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
HTML_OBJECT_PATTERN = re.compile(
    r'<object[^>]+data=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
HTML_HREF_PATTERN = re.compile(
    r'<a[^>]+href=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
SCRIPT_PDF_URL_PATTERN = re.compile(
    r'["\']([^"\']*(?:\.pdf(?:[?#][^"\']*)?|/doi/(?:pdf|pdfdirect|epdf)/[^"\']*|download=true[^"\']*))["\']',
    re.IGNORECASE,
)
HTML_CONTENT_TYPE_MARKERS: tuple[str, ...] = (
    "text/html",
    "application/xhtml+xml",
)
PDF_RESOLUTION_MAX_DEPTH: int = 2
PDF_CANDIDATE_PREFIXES: tuple[str, ...] = (
    "/doi/pdf/",
    "/doi/pdfdirect/",
    "/doi/epdf/",
)
INCOMPLETE_READ_RETRY_COUNT: int = 3
HttpFetcher: TypeAlias = Callable[
    [str, int, str, str | None],
    "BinaryHttpResponse",
]


class DownloadError(RuntimeError):
    """Raised when a DOI download cannot be saved as a valid PDF."""


@dataclass(frozen=True)
class DownloadConfig:
    """Runtime configuration for DOI downloads."""

    base_urls: tuple[str, ...]
    pdf_root_dir: Path
    timeout_seconds: int
    user_agent: str = DEFAULT_HTTP_USER_AGENT
    inter_download_sleep_seconds: float = 3.0


@dataclass(frozen=True)
class BinaryHttpResponse:
    """Small response container used by the downloader and tests."""

    url: str
    status_code: int
    headers: dict[str, str]
    body: bytes


def build_doi_download_url(
    base_url: str,
    doi: str,
) -> str:
    """Build one DOI download URL."""
    normalized_base_url = base_url.rstrip("/")
    encoded_doi = quote(doi, safe="/")
    return f"{normalized_base_url}/{encoded_doi}"


def build_doi_download_urls(
    base_urls: tuple[str, ...],
    doi: str,
) -> list[str]:
    """Build one candidate download URL per configured base URL."""
    return [
        build_doi_download_url(
            base_url=base_url,
            doi=doi,
        )
        for base_url in base_urls
    ]


def rotate_base_urls(
    base_urls: tuple[str, ...],
    start_index: int,
) -> tuple[str, ...]:
    """Rotate the base-URL order so one index becomes the first attempt."""
    if not base_urls:
        return ()

    normalized_start_index = start_index % len(base_urls)
    rotated_base_urls = base_urls[normalized_start_index:]
    wrapped_base_urls = base_urls[:normalized_start_index]
    return rotated_base_urls + wrapped_base_urls


def fetch_binary_response(
    url: str,
    timeout_seconds: int,
    user_agent: str,
    referer: str | None = None,
) -> BinaryHttpResponse:
    """Fetch one binary HTTP payload."""
    request_headers = {
        "User-Agent": user_agent,
        "Accept": "application/pdf,text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    }

    # The viewer page sometimes requires the article page as a referer before
    # the direct PDF endpoint will return bytes instead of a landing page.
    if referer is not None:
        request_headers["Referer"] = referer

    # Some publisher endpoints close the socket before the declared body length
    # arrives. Retry a few times before treating that partial transfer as a
    # hard failure. The final attempt re-raises, so the loop always exits by
    # returning or raising.
    for attempt_number in range(INCOMPLETE_READ_RETRY_COUNT):
        request = Request(url, headers=request_headers, method="GET")

        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                headers = {
                    key.lower(): value for key, value in response.headers.items()
                }
                body = response.read()
                status_code = getattr(response, "status", 200)
                final_url = response.geturl()
        except IncompleteRead:
            if attempt_number + 1 >= INCOMPLETE_READ_RETRY_COUNT:
                raise

            continue

        return BinaryHttpResponse(
            url=final_url,
            status_code=status_code,
            headers=headers,
            body=body,
        )


def pdf_bytes_look_valid(pdf_bytes: bytes) -> bool:
    """Return `True` when the payload looks like a real PDF."""
    if len(pdf_bytes) < naming.PDF_MIN_VALID_SIZE_BYTES:
        return False

    if not pdf_bytes.startswith(naming.PDF_MAGIC_PREFIX):
        return False

    return True


def response_looks_html(response: BinaryHttpResponse) -> bool:
    """Return `True` when the payload appears to be HTML instead of PDF."""
    content_type = response.headers.get("content-type", "").lower()

    if any(marker in content_type for marker in HTML_CONTENT_TYPE_MARKERS):
        return True

    body_prefix = response.body[:256].lstrip().lower()

    if body_prefix.startswith(b"<!doctype html"):
        return True

    if body_prefix.startswith(b"<html"):
        return True

    return False


def extract_filename_from_content_disposition(
    content_disposition: str | None,
) -> str | None:
    """Extract a filename from one `Content-Disposition` header."""
    if not content_disposition:
        return None

    filename_star_match = CONTENT_DISPOSITION_FILENAME_STAR_PATTERN.search(
        content_disposition
    )

    if filename_star_match is not None:
        return unquote(filename_star_match.group(1).strip().strip('"'))

    filename_match = CONTENT_DISPOSITION_FILENAME_PATTERN.search(content_disposition)

    if filename_match is not None:
        return filename_match.group(1).strip()

    return None


def infer_filename_from_url(url: str) -> str | None:
    """Infer a filename from the final URL path segment."""
    parsed_url = urlparse(url)
    decoded_path = unquote(parsed_url.path)
    path_name = Path(decoded_path).name

    if not path_name:
        return None

    if "." not in path_name:
        return None

    return path_name


def candidate_url_looks_pdf_like(candidate_url: str) -> bool:
    """Return `True` when a URL string looks worth trying as a PDF target."""
    parsed_url = urlparse(candidate_url)
    lowered_path = parsed_url.path.lower()
    lowered_query = parsed_url.query.lower()

    if lowered_path.endswith(".pdf"):
        return True

    if any(prefix in lowered_path for prefix in PDF_CANDIDATE_PREFIXES):
        return True

    if "download=true" in lowered_query:
        return True

    return False


def normalize_pdf_candidate_url(raw_candidate_url: str, page_url: str) -> str | None:
    """Normalize one extracted HTML candidate into an absolute URL."""
    candidate_url = unescape(raw_candidate_url).strip()

    if not candidate_url:
        return None

    if candidate_url.startswith(("javascript:", "mailto:", "#")):
        return None

    absolute_candidate_url = urljoin(page_url, candidate_url)

    if candidate_url_looks_pdf_like(absolute_candidate_url):
        return absolute_candidate_url

    parsed_url = urlparse(absolute_candidate_url)
    query_values = parse_qs(parsed_url.query)

    for key in ("file", "pdf", "download", "url", "src"):
        raw_query_values = query_values.get(key)

        if raw_query_values is None:
            continue

        for raw_query_value in raw_query_values:
            resolved_query_url = urljoin(page_url, unquote(raw_query_value))

            if candidate_url_looks_pdf_like(resolved_query_url):
                return resolved_query_url

    return None


def extract_pdf_candidate_urls(html_text: str, page_url: str) -> list[str]:
    """Extract likely PDF or PDF-viewer target URLs from one HTML page."""
    candidate_urls: list[str] = []
    seen_urls: set[str] = set()

    def add_candidate(raw_candidate_url: str) -> None:
        normalized_candidate_url = normalize_pdf_candidate_url(
            raw_candidate_url=raw_candidate_url,
            page_url=page_url,
        )

        if normalized_candidate_url is None:
            return

        if normalized_candidate_url in seen_urls:
            return

        seen_urls.add(normalized_candidate_url)
        candidate_urls.append(normalized_candidate_url)

    for match in HTML_CITATION_PDF_URL_PATTERN.finditer(html_text):
        add_candidate(match.group(1))

    for match in HTML_IFRAME_EMBED_PATTERN.finditer(html_text):
        add_candidate(match.group(1))

    for match in HTML_OBJECT_PATTERN.finditer(html_text):
        add_candidate(match.group(1))

    for match in HTML_HREF_PATTERN.finditer(html_text):
        add_candidate(match.group(1))

    for match in SCRIPT_PDF_URL_PATTERN.finditer(html_text):
        add_candidate(match.group(1))

    return candidate_urls


def resolve_pdf_response(
    response: BinaryHttpResponse,
    timeout_seconds: int,
    user_agent: str,
    fetcher: Callable[[str, int, str, str | None], BinaryHttpResponse],
    *,
    referer: str | None = None,
    visited_urls: set[str] | None = None,
    depth: int = 0,
) -> BinaryHttpResponse:
    """Resolve a valid PDF response from direct bytes or an HTML viewer page.

    Parameters
    ----------
    response:
        Initial HTTP response for one DOI candidate URL.
    timeout_seconds:
        HTTP timeout used for follow-up candidate requests.
    user_agent:
        User-Agent header value reused for follow-up candidate requests.
    fetcher:
        HTTP transport callable used for follow-up candidate requests.
    referer:
        Compatibility parameter kept for older callers. Follow-up requests use
        the immediate parent response URL as the effective referer.
    visited_urls:
        URLs already visited in this recursion chain to prevent loops.
    depth:
        Current recursion depth for HTML-to-PDF resolution.

    Returns
    -------
    BinaryHttpResponse
        First response with valid PDF bytes, or the best unresolved response
        when no valid PDF can be found.
    """
    # Fast-path exit for real PDF bytes.
    if pdf_bytes_look_valid(response.body):
        return response

    # Non-HTML responses have no further candidate links to follow.
    if not response_looks_html(response):
        return response

    # Stop recursion once the configured safety depth is reached.
    if depth >= PDF_RESOLUTION_MAX_DEPTH:
        return response

    html_text = response.body.decode("utf-8", errors="replace")
    candidate_urls = extract_pdf_candidate_urls(html_text, response.url)

    if visited_urls is None:
        # Seed the visited set with the current response URL.
        visited_urls = {response.url}
    else:
        # Copy before mutation so sibling branches do not share state.
        visited_urls = set(visited_urls)
        visited_urls.add(response.url)

    for candidate_url in candidate_urls:
        if candidate_url in visited_urls:
            continue

        candidate_response = fetcher(
            candidate_url,
            timeout_seconds,
            user_agent,
            response.url,
        )
        resolved_candidate_response = resolve_pdf_response(
            candidate_response,
            timeout_seconds,
            user_agent,
            fetcher,
            referer=response.url,
            visited_urls=visited_urls | {candidate_url},
            depth=depth + 1,
        )

        if pdf_bytes_look_valid(resolved_candidate_response.body):
            return resolved_candidate_response

    return response


def choose_base_filename(
    response: BinaryHttpResponse,
    metadata_title: str | None = None,
) -> str:
    """Choose the base filename before appending the DOI marker.

    Parameters
    ----------
    response:
        Validated PDF response, used for its `Content-Disposition` header and
        final URL.
    metadata_title:
        Article title from DOI metadata, or ``None`` when the lookup found no
        title or could not run.

    Returns
    -------
    str
        A `*.pdf` filename. The metadata title is preferred; otherwise the name
        the server suggested, falling back to ``article.pdf``.
    """
    content_disposition = response.headers.get("content-disposition")
    response_filename = extract_filename_from_content_disposition(content_disposition)

    if response_filename is None:
        response_filename = infer_filename_from_url(response.url)

    if response_filename is None:
        response_filename = "article.pdf"

    if Path(response_filename).suffix.lower() != ".pdf":
        response_filename = "article.pdf"

    # Metadata is useful for readable filenames, but it is optional. A PDF that
    # has already been fetched and validated should still be saved if Crossref
    # or OpenAlex is temporarily unavailable.
    if metadata_title is not None:
        title_stem = naming.sanitize_title_for_filename(metadata_title)

        if title_stem is not None:
            return f"{title_stem}.pdf"

    return response_filename


def build_output_dir(
    pdf_root_dir: Path,
    issn: str | None,
    publication_year: str | None,
) -> Path:
    """Build the output directory for one DOI."""
    if issn is None and publication_year is None:
        return pdf_root_dir

    if issn is None:
        return pdf_root_dir / publication_year

    if publication_year is None:
        return pdf_root_dir / issn

    return pdf_root_dir / issn / publication_year


def build_temp_pdf_path(output_dir: Path, doi: str) -> Path:
    """Build the temporary PDF path used before atomic rename."""
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    safe_doi = naming.sanitize_doi_for_filename(doi)
    return output_dir / f".partial_{timestamp}_{safe_doi}.pdf"


def save_pdf_response(
    doi: str,
    issn: str | None,
    response: BinaryHttpResponse,
    config: DownloadConfig,
) -> Path:
    """Validate and save one PDF response."""
    if response.status_code != 200:
        raise DownloadError(f"HTTP {response.status_code} for DOI {doi}")

    content_type = response.headers.get("content-type", "")
    response_body = response.body

    # Some servers mislabel PDFs, so the bytes are the final source of truth.
    if not pdf_bytes_look_valid(response_body):
        raise DownloadError(
            f"Response for DOI {doi} is not a valid PDF; content-type={content_type}"
        )

    metadata_title: str | None = None
    publication_year: str | None = None

    # Metadata only affects the readable filename and optional year folder.
    # Once the PDF bytes are valid, a metadata outage should not block the save,
    # so the DOI keeps its fallback filename and lands directly under the ISSN.
    with suppress(Exception):
        metadata_title, publication_year = naming.lookup_doi_metadata(doi)

    output_dir = build_output_dir(config.pdf_root_dir, issn, publication_year)
    output_dir.mkdir(parents=True, exist_ok=True)

    base_filename = choose_base_filename(
        response=response,
        metadata_title=metadata_title,
    )
    target_filename = naming.build_target_pdf_filename(base_filename, doi)
    target_path = output_dir / target_filename

    if target_path.exists():
        return target_path

    temp_path = build_temp_pdf_path(output_dir, doi)

    with temp_path.open("wb") as temp_file:
        temp_file.write(response_body)

    temp_path.replace(target_path)
    return target_path


def download_one_doi(
    doi: str,
    issn: str | None,
    config: DownloadConfig,
    fetcher: HttpFetcher = fetch_binary_response,
) -> Path:
    """Download and save one DOI as a PDF.

    Parameters
    ----------
    doi:
        DOI to download.
    issn:
        Journal ISSN used to build the output directory hierarchy.
    config:
        Active download configuration.
    fetcher:
        Injectable HTTP fetcher; defaults to :func:`fetch_binary_response`.
    """
    attempted_error_messages: list[str] = []
    ordered_base_urls = config.base_urls

    # Randomize which configured base URL gets the first attempt for each DOI,
    # then exhaust the remaining URLs in wrapped order.
    if len(config.base_urls) > 1:
        starting_base_url_index = random.randrange(len(config.base_urls))
        ordered_base_urls = rotate_base_urls(
            config.base_urls,
            starting_base_url_index,
        )

    download_urls = build_doi_download_urls(
        base_urls=ordered_base_urls,
        doi=doi,
    )

    for download_url in download_urls:
        try:
            response = fetcher(
                download_url,
                config.timeout_seconds,
                config.user_agent,
                None,
            )
            resolved_response = resolve_pdf_response(
                response,
                config.timeout_seconds,
                config.user_agent,
                fetcher,
                referer=None,
            )
            return save_pdf_response(
                doi=doi,
                issn=issn,
                response=resolved_response,
                config=config,
            )
        except Exception as exc:  # noqa: BLE001
            attempted_error_messages.append(f"{download_url} -> {exc}")

    joined_errors = "; ".join(attempted_error_messages)
    raise DownloadError(
        f"All configured base URLs failed for DOI {doi}: {joined_errors}"
    )


def _prepare_resumable_download(
    dois: list[str],
    progress_files: BatchProgressFiles,
    config: DownloadConfig,
    retry_error_dois: bool,
) -> tuple[list[str], set[str], set[str]]:
    """Reconcile queue, ledgers, and on-disk PDFs before one resumable batch.

    Returns
    -------
    tuple[list[str], set[str], set[str]]
        Pending DOI worklist plus mutable success and error ledger sets used by
        :func:`run_download_pass`.
    """
    successful_logged_dois = load_logged_doi_list(progress_files.success_path)
    errored_logged_dois = load_logged_doi_list(progress_files.error_path)
    resume_decisions = reconcile_pending_dois(
        source_dois=dois,
        successful_logged_dois=successful_logged_dois,
        errored_logged_dois=errored_logged_dois,
        output_root_dir=config.pdf_root_dir,
        retry_error_dois=retry_error_dois,
    )

    if resume_decisions.skipped_error_dois:
        skipped_error_count = len(resume_decisions.skipped_error_dois)
        print(
            f"Skipping {skipped_error_count} DOI(s) already recorded in "
            f"{progress_files.error_path}. Pass --retry-error-dois to retry them."
        )

    # Existing PDFs are terminal successes and should leave the mutable queue.
    if resume_decisions.existing_pdf_dois:
        remove_dois_from_source_queue(
            progress_files.source_path,
            resume_decisions.existing_pdf_dois,
        )
        remove_dois_from_log(
            progress_files.error_path,
            resume_decisions.existing_pdf_dois,
        )

    existing_success_set = set(successful_logged_dois)
    unlogged_existing_dois = [
        existing_doi
        for existing_doi in resume_decisions.existing_pdf_dois
        if existing_doi not in existing_success_set
    ]
    append_progress_entries(
        progress_files.success_path,
        unlogged_existing_dois,
        {"status": "existing_pdf"},
    )
    existing_success_set.update(unlogged_existing_dois)

    # Stale success rows claim a PDF that no longer exists on disk.
    if resume_decisions.stale_success_dois:
        remove_dois_from_log(
            progress_files.success_path,
            resume_decisions.stale_success_dois,
        )
        stale_success_set = set(resume_decisions.stale_success_dois)
        successful_logged_dois = [
            doi for doi in successful_logged_dois if doi not in stale_success_set
        ]

    return (
        resume_decisions.pending_dois,
        set(successful_logged_dois),
        set(errored_logged_dois),
    )


def run_download_pass(
    dois: list[str],
    issn: str | None,
    config: DownloadConfig,
    progress_files: BatchProgressFiles | None,
    successful_dois: set[str],
    errored_dois: set[str],
    fetcher: Callable[[str, int, str, str | None], BinaryHttpResponse],
    sleep_fn: Callable[[float], None],
    pass_label: str | None = None,
) -> list[str]:
    """Run one ordered download pass and return the DOI values still failing.

    Parameters
    ----------
    dois:
        Ordered DOI list for this pass.
    issn:
        Journal ISSN used to build the PDF output hierarchy.
    config:
        Runtime download configuration.
    progress_files:
        Optional queue and ledger paths for resumable runs.
    successful_dois:
        Mutable set of DOI values already recorded as successful.
    errored_dois:
        Mutable set of DOI values already recorded in the error ledger.
    fetcher:
        HTTP transport used in direct mode.
    sleep_fn:
        Sleep function used between DOI downloads.
    pass_label:
        Optional label such as ``"retry"`` printed in progress lines.
    """
    failed_dois: list[str] = []
    resolved_error_dois: set[str] = set()
    total_dois = len(dois)
    normalized_label = "" if pass_label is None else f"{pass_label} "

    for doi_index, doi in enumerate(dois, start=1):
        try:
            saved_pdf_path = download_one_doi(
                doi=doi,
                issn=issn,
                config=config,
                fetcher=fetcher,
            )
        except Exception as exc:  # noqa: BLE001
            failed_dois.append(doi)
            record_batch_outcome(
                progress_files=progress_files,
                successful_dois=successful_dois,
                errored_dois=errored_dois,
                doi=doi,
                status="download_error",
                resolved_error_dois=resolved_error_dois,
            )
            print(f"[{normalized_label}{doi_index}/{total_dois}] failed {doi}: {exc}")
        else:
            record_batch_outcome(
                progress_files=progress_files,
                successful_dois=successful_dois,
                errored_dois=errored_dois,
                doi=doi,
                status="success",
                resolved_error_dois=resolved_error_dois,
                pdf_path=saved_pdf_path,
            )
            print(
                f"[{normalized_label}{doi_index}/{total_dois}] saved {saved_pdf_path}"
            )

        if doi_index >= total_dois:
            continue

        sleep_fn(config.inter_download_sleep_seconds)

    # Clear the error ledger once for every DOI that succeeded after failing,
    # instead of rewriting the whole file per DOI inside the loop.
    if progress_files is not None and resolved_error_dois:
        remove_dois_from_log(progress_files.error_path, resolved_error_dois)

    return failed_dois


def run_download_batch(
    dois: list[str],
    issn: str | None,
    config: DownloadConfig,
    progress_files: BatchProgressFiles | None = None,
    retry_error_dois: bool = False,
    fetcher: Callable[
        [str, int, str, str | None], BinaryHttpResponse
    ] = fetch_binary_response,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> int:
    """Run one DOI batch download.

    Returns `0` when every attempted DOI succeeds by the end of the batch.

    The batch uses up to two passes:

    1. Process the current DOI queue.
    2. Retry the DOI values that failed in the first pass once more after the
       queue is exhausted.
    """
    if progress_files is None:
        pending_dois = dois
        successful_dois: set[str] = set()
        errored_dois: set[str] = set()
    else:
        pending_dois, successful_dois, errored_dois = _prepare_resumable_download(
            dois=dois,
            progress_files=progress_files,
            config=config,
            retry_error_dois=retry_error_dois,
        )

    failed_dois = run_download_pass(
        dois=pending_dois,
        issn=issn,
        config=config,
        progress_files=progress_files,
        successful_dois=successful_dois,
        errored_dois=errored_dois,
        fetcher=fetcher,
        sleep_fn=sleep_fn,
    )

    if progress_files is not None and failed_dois:
        print(f"Retrying {len(failed_dois)} DOI(s) from {progress_files.error_path}")
        failed_dois = run_download_pass(
            dois=failed_dois,
            issn=issn,
            config=config,
            progress_files=progress_files,
            successful_dois=successful_dois,
            errored_dois=errored_dois,
            fetcher=fetcher,
            sleep_fn=sleep_fn,
            pass_label="retry",
        )

    # Remove all processed DOIs from the queue in one pass rather than per-DOI.
    if progress_files is not None and pending_dois:
        remove_dois_from_source_queue(progress_files.source_path, pending_dois)

    return 0 if not failed_dois else 1
