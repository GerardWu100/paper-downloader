"""DOI-to-CSV metadata export helpers.

This module is intentionally separate from the PDF downloader. Its job is to:

1. Read DOI values from an existing DOI queue file.
2. Query Crossref and OpenAlex for article metadata.
3. Merge the useful fields into one flat CSV row per DOI.

The current export focuses on fields that are convenient for screening and
lightweight downstream analysis:

- DOI
- human-readable title
- abstract
- authors
- ORCID IDs
- affiliations
- published date
- journal title
- publisher
- keywords
- topics
"""

from __future__ import annotations

import csv
import html
import re
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TextIO
from urllib.parse import urlsplit

from .. import naming
from .._http import JsonObject, extract_object_list
from .._http import fetch_json_payload as _core_fetch_json_payload
from ..progress import strip_queue_file_suffix
from ..providers import crossref, openalex

DEFAULT_TIMEOUT_SECONDS: int = 60
DEFAULT_METADATA_MAX_WORKERS: int = 8
# OpenAlex documents a 10 requests-per-second ceiling per contact address,
# and the pacer spaces request starts per provider host, so 0.1s keeps the
# worker pool at that ceiling instead of twice it.
DEFAULT_REQUEST_DELAY_SECONDS: float = 0.1
MARKUP_TAG_PATTERN = re.compile(r"<[^>]+>")
ORCID_URL_PREFIX_PATTERN = re.compile(r"^https?://orcid\.org/", re.IGNORECASE)

JsonFetcher = Callable[[str, dict[str, str] | None, int], JsonObject]
Sleeper = Callable[[float], None]
Clock = Callable[[], float]


@dataclass(frozen=True)
class MetadataRecord:
    """Store one flat metadata row ready for CSV export.

    Parameters
    ----------
    doi:
        Canonical DOI string for the article.
    title:
        Human-readable article title.
    abstract:
        Plain-text abstract. OpenAlex abstracts are reconstructed from the
        inverted-index representation.
    authors:
        Semicolon-delimited author display names.
    orcid_ids:
        Semicolon-delimited ORCID identifiers.
    affiliations:
        Semicolon-delimited author-to-affiliation mappings.
    published_date:
        ISO-like publication date string such as `2024-01-15` or `2024-01`.
    journal_title:
        Journal or source title for the article.
    publisher:
        Publisher name when known.
    keywords:
        Semicolon-delimited keyword names.
    topics:
        Semicolon-delimited topic or subject-area names.
    """

    doi: str
    title: str
    abstract: str
    authors: str
    orcid_ids: str
    affiliations: str
    published_date: str
    journal_title: str
    publisher: str
    keywords: str
    topics: str


def fetch_json_payload(
    url: str,
    headers: dict[str, str] | None,
    timeout_seconds: int,
) -> JsonObject:
    """Fetch one JSON object from HTTP.

    This is the positional-argument form of `_http.fetch_json_payload` that the
    `JsonFetcher` alias expects, so injected test fetchers and the real one
    share a signature.
    """
    return _core_fetch_json_payload(
        url,
        headers=headers,
        timeout_seconds=timeout_seconds,
    )


def _normalize_text(raw_text: object) -> str:
    """Normalize one free-form string field into single-spaced text."""
    if not isinstance(raw_text, str):
        return ""

    return " ".join(raw_text.split())


def _join_normalized_name_parts(*parts: object) -> str:
    """Join name fragments after trimming whitespace and dropping blanks."""
    normalized_parts: list[str] = []

    for part in parts:
        normalized_part = _normalize_text(part)

        if normalized_part:
            normalized_parts.append(normalized_part)

    return " ".join(normalized_parts)


def _extract_display_name_list(
    container: JsonObject,
    list_field_name: str,
    name_field_name: str,
) -> str:
    """Collect one semicolon-delimited list of normalized display names."""
    normalized_values = [
        _normalize_text(raw_item.get(name_field_name))
        for raw_item in extract_object_list(container, list_field_name)
    ]
    return "; ".join(value for value in normalized_values if value)


def _first_nonempty(*values: str) -> str:
    """Return the first non-empty string from one ordered fallback chain."""
    for value in values:
        if value:
            return value

    return ""


class MetadataRequestPacer:
    """Space metadata API requests by host across worker threads.

    Parameters
    ----------
    request_delay_seconds:
        Minimum gap between request starts for the same hostname. For example,
        a value of ``0.05`` caps one host at roughly 20 request starts per
        second, before provider-side latency is considered.
    sleep:
        Function used to pause the current worker. Tests inject a fake sleeper
        so pacing can be verified without slowing the suite.
    monotonic:
        Monotonic clock function used for elapsed-time calculations.

    Notes
    -----
    The pacer is host-aware: Crossref and OpenAlex each get their own clock.
    This avoids a tight request burst to either provider while still allowing
    independent providers to make progress at the same time.
    """

    def __init__(
        self,
        request_delay_seconds: float,
        sleep: Sleeper = time.sleep,
        monotonic: Clock = time.monotonic,
    ) -> None:
        """Initialize per-host pacing state."""
        self.request_delay_seconds = max(0.0, request_delay_seconds)
        self.sleep = sleep
        self.monotonic = monotonic
        self.lock = threading.Lock()
        self.next_request_time_by_host: dict[str, float] = {}

    def wait_for_turn(self, url: str) -> None:
        """Sleep until this URL's hostname can start another request."""
        if self.request_delay_seconds <= 0.0:
            return

        hostname = urlsplit(url).hostname or ""

        if not hostname:
            return

        with self.lock:
            current_time = self.monotonic()
            next_request_time = self.next_request_time_by_host.get(
                hostname,
                current_time,
            )
            sleep_seconds = max(0.0, next_request_time - current_time)
            scheduled_time = max(current_time, next_request_time)
            self.next_request_time_by_host[hostname] = (
                scheduled_time + self.request_delay_seconds
            )

        if sleep_seconds > 0.0:
            self.sleep(sleep_seconds)


def build_paced_json_fetcher(
    fetch_json: JsonFetcher,
    request_delay_seconds: float,
    sleep: Sleeper = time.sleep,
    monotonic: Clock = time.monotonic,
) -> JsonFetcher:
    """Wrap a JSON fetcher with per-host request pacing.

    Parameters
    ----------
    fetch_json:
        Existing JSON fetch function with the project-standard signature.
    request_delay_seconds:
        Minimum gap between request starts for the same provider host.
    sleep:
        Sleep function used by the pacer.
    monotonic:
        Monotonic clock function used by the pacer.

    Returns
    -------
    JsonFetcher
        Fetch function that waits for the provider host's next available
        request slot before delegating to ``fetch_json``.
    """
    if request_delay_seconds <= 0.0:
        return fetch_json

    pacer = MetadataRequestPacer(
        request_delay_seconds=request_delay_seconds,
        sleep=sleep,
        monotonic=monotonic,
    )

    def paced_fetch_json(
        url: str,
        headers: dict[str, str] | None,
        timeout_seconds: int,
    ) -> JsonObject:
        """Wait for this URL's provider host before fetching JSON."""
        pacer.wait_for_turn(url)
        return fetch_json(url, headers, timeout_seconds)

    return paced_fetch_json


def fetch_crossref_work(
    doi: str,
    email: str,
    timeout_seconds: int,
    fetch_json: JsonFetcher = fetch_json_payload,
) -> JsonObject | None:
    """Fetch one Crossref `message` object for a DOI."""
    payload = fetch_json(
        crossref.build_work_url(doi),
        crossref.build_polite_headers(email),
        timeout_seconds,
    )
    message_object = payload.get("message")

    if not isinstance(message_object, dict):
        return None

    return message_object


def fetch_openalex_work(
    doi: str,
    timeout_seconds: int,
    email: str | None = None,
    fetch_json: JsonFetcher = fetch_json_payload,
) -> JsonObject | None:
    """Fetch one OpenAlex work object for a DOI."""
    payload = fetch_json(
        openalex.build_work_url(doi, email),
        openalex.build_headers(email),
        timeout_seconds,
    )

    if not isinstance(payload, dict):
        return None

    return payload


def strip_markup(raw_text: str) -> str:
    """Convert small XML or HTML fragments into plain text."""
    text_without_tags = MARKUP_TAG_PATTERN.sub(" ", raw_text)
    unescaped_text = html.unescape(text_without_tags)
    normalized_text = " ".join(unescaped_text.split())
    return normalized_text


def normalize_orcid(raw_orcid: object) -> str:
    """Normalize one ORCID value into the bare identifier form."""
    if not isinstance(raw_orcid, str):
        return ""

    stripped_orcid = raw_orcid.strip()

    if not stripped_orcid:
        return ""

    return ORCID_URL_PREFIX_PATTERN.sub("", stripped_orcid)


def extract_crossref_abstract(message_object: JsonObject | None) -> str:
    """Return the plain-text Crossref abstract when present."""
    if message_object is None:
        return ""

    raw_abstract = message_object.get("abstract")

    if not isinstance(raw_abstract, str):
        return ""

    return strip_markup(raw_abstract)


def reconstruct_openalex_abstract(inverted_index: JsonObject) -> str:
    """Rebuild plain text from the OpenAlex abstract inverted index."""
    ordered_tokens: dict[int, list[str]] = {}

    for raw_token, raw_positions in inverted_index.items():
        if not isinstance(raw_token, str):
            continue

        if not isinstance(raw_positions, list):
            continue

        # Each token can appear at multiple integer positions.
        for raw_position in raw_positions:
            if not isinstance(raw_position, int):
                continue

            # OpenAlex normally assigns one token per position, but provider
            # data can contain collisions. Keep every token instead of letting
            # the later dictionary assignment silently erase the earlier one.
            tokens_at_position = ordered_tokens.setdefault(raw_position, [])
            tokens_at_position.append(raw_token)

    if not ordered_tokens:
        return ""

    sorted_positions = sorted(ordered_tokens)
    ordered_words: list[str] = []

    for position in sorted_positions:
        ordered_words.extend(ordered_tokens[position])

    return " ".join(ordered_words)


def extract_openalex_abstract(openalex_work: JsonObject | None) -> str:
    """Return the reconstructed OpenAlex abstract when present."""
    if openalex_work is None:
        return ""

    raw_inverted_index = openalex_work.get("abstract_inverted_index")

    if not isinstance(raw_inverted_index, dict):
        return ""

    return reconstruct_openalex_abstract(raw_inverted_index)


@dataclass(frozen=True)
class AuthorRow:
    """One author's contribution to a work, in a provider-independent shape.

    Crossref and OpenAlex nest author data differently, so each provider gets a
    small adapter that flattens its payload into these rows. The formatters
    below then work for both providers.

    Parameters
    ----------
    name:
        Author display name. Empty when the provider supplied no usable name;
        the affiliation formatter still emits the affiliations in that case.
    orcid:
        Bare ORCID identifier, or an empty string when absent.
    affiliations:
        Institution names for this author, in provider order.
    """

    name: str
    orcid: str
    affiliations: tuple[str, ...]


def _unique_normalized_names(
    raw_items: list[JsonObject],
    field_name: str,
) -> tuple[str, ...]:
    """Collect normalized display names from one object list, dropping repeats."""
    collected_names: list[str] = []
    seen_names: set[str] = set()

    for raw_item in raw_items:
        normalized_name = _normalize_text(raw_item.get(field_name))

        if not normalized_name or normalized_name in seen_names:
            continue

        seen_names.add(normalized_name)
        collected_names.append(normalized_name)

    return tuple(collected_names)


def crossref_author_rows(message_object: JsonObject | None) -> list[AuthorRow]:
    """Flatten the Crossref `author` list into provider-independent rows."""
    if message_object is None:
        return []

    return [
        AuthorRow(
            name=_join_normalized_name_parts(
                raw_author.get("given"),
                raw_author.get("family"),
            ),
            orcid=normalize_orcid(raw_author.get("ORCID")),
            affiliations=_unique_normalized_names(
                extract_object_list(raw_author, "affiliation"), "name"
            ),
        )
        for raw_author in extract_object_list(message_object, "author")
    ]


def openalex_author_rows(openalex_work: JsonObject | None) -> list[AuthorRow]:
    """Flatten the OpenAlex `authorships` list into provider-independent rows.

    OpenAlex splits each contribution into an `author` object (name, ORCID) and
    a sibling `institutions` list, so the two are recombined here.
    """
    if openalex_work is None:
        return []

    author_rows: list[AuthorRow] = []

    for raw_authorship in extract_object_list(openalex_work, "authorships"):
        raw_author = raw_authorship.get("author")

        if not isinstance(raw_author, dict):
            raw_author = {}

        author_rows.append(
            AuthorRow(
                name=_normalize_text(raw_author.get("display_name")),
                orcid=normalize_orcid(raw_author.get("orcid")),
                affiliations=_unique_normalized_names(
                    extract_object_list(raw_authorship, "institutions"), "display_name"
                ),
            )
        )

    return author_rows


def format_author_names(author_rows: list[AuthorRow]) -> str:
    """Return a semicolon-delimited list of author names."""
    return "; ".join(row.name for row in author_rows if row.name)


def format_orcid_ids(author_rows: list[AuthorRow]) -> str:
    """Return a semicolon-delimited list of unique ORCID identifiers."""
    unique_orcids: list[str] = []
    seen_orcids: set[str] = set()

    for row in author_rows:
        if not row.orcid or row.orcid in seen_orcids:
            continue

        seen_orcids.add(row.orcid)
        unique_orcids.append(row.orcid)

    return "; ".join(unique_orcids)


def format_affiliations(author_rows: list[AuthorRow]) -> str:
    """Return author-to-affiliation mappings as `name: inst1, inst2; ...`.

    Authors with no affiliations are omitted. An affiliated author with no
    usable name contributes just the institution list, with no `name:` prefix.
    """
    formatted_authors: list[str] = []

    for row in author_rows:
        if not row.affiliations:
            continue

        joined_affiliations = ", ".join(row.affiliations)

        if row.name:
            formatted_authors.append(f"{row.name}: {joined_affiliations}")
        else:
            formatted_authors.append(joined_affiliations)

    return "; ".join(formatted_authors)


def extract_openalex_published_date(openalex_work: JsonObject | None) -> str:
    """Return the OpenAlex publication date string when present."""
    if openalex_work is None:
        return ""

    publication_date = openalex_work.get("publication_date")

    if not isinstance(publication_date, str):
        return ""

    return publication_date.strip()


def extract_crossref_journal_title(message_object: JsonObject | None) -> str:
    """Return the journal title from Crossref container metadata."""
    if message_object is None:
        return ""

    return naming.normalize_title_text(message_object.get("container-title")) or ""


def extract_openalex_journal_title(openalex_work: JsonObject | None) -> str:
    """Return the journal title from the OpenAlex primary location."""
    if openalex_work is None:
        return ""

    raw_primary_location = openalex_work.get("primary_location")

    if not isinstance(raw_primary_location, dict):
        return ""

    raw_source = raw_primary_location.get("source")

    if isinstance(raw_source, dict):
        display_name = _normalize_text(raw_source.get("display_name"))

        if display_name:
            return display_name

    raw_source_name = raw_primary_location.get("raw_source_name")

    if not isinstance(raw_source_name, str):
        return ""

    return _normalize_text(raw_source_name)


def extract_crossref_publisher(message_object: JsonObject | None) -> str:
    """Return the publisher name from Crossref."""
    if message_object is None:
        return ""

    return _normalize_text(message_object.get("publisher"))


def extract_openalex_publisher(openalex_work: JsonObject | None) -> str:
    """Return the publisher name from OpenAlex source metadata."""
    if openalex_work is None:
        return ""

    raw_primary_location = openalex_work.get("primary_location")

    if not isinstance(raw_primary_location, dict):
        return ""

    raw_source = raw_primary_location.get("source")

    if not isinstance(raw_source, dict):
        return ""

    return _normalize_text(raw_source.get("host_organization_name"))


def extract_crossref_keywords(message_object: JsonObject | None) -> str:
    """Return a semicolon-delimited keyword string from Crossref subjects."""
    if message_object is None:
        return ""

    raw_subjects = message_object.get("subject")

    if not isinstance(raw_subjects, list):
        return ""

    normalized_subjects: list[str] = []

    for raw_subject in raw_subjects:
        normalized_subject = _normalize_text(raw_subject)

        if normalized_subject:
            normalized_subjects.append(normalized_subject)

    return "; ".join(normalized_subjects)


def extract_openalex_keywords(openalex_work: JsonObject | None) -> str:
    """Return a semicolon-delimited keyword string from OpenAlex."""
    if openalex_work is None:
        return ""

    return _extract_display_name_list(openalex_work, "keywords", "display_name")


def extract_openalex_topics(openalex_work: JsonObject | None) -> str:
    """Return a semicolon-delimited topic string from OpenAlex."""
    if openalex_work is None:
        return ""

    return _extract_display_name_list(openalex_work, "topics", "display_name")


def build_metadata_record(
    doi: str,
    email: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    fetch_json: JsonFetcher = fetch_json_payload,
) -> MetadataRecord:
    """Query both providers and merge the selected metadata fields."""
    crossref_error: Exception | None = None
    openalex_error: Exception | None = None

    try:
        crossref_message = fetch_crossref_work(
            doi=doi,
            email=email,
            timeout_seconds=timeout_seconds,
            fetch_json=fetch_json,
        )
    except Exception as exc:  # noqa: BLE001
        # Crossref is the preferred source for bibliographic fields, but one
        # provider outage should not prevent the other provider from filling the
        # row. The outer exporter still writes a blank row only if both provider
        # fetches and record construction fail.
        crossref_error = exc
        crossref_message = None

    try:
        openalex_work = fetch_openalex_work(
            doi=doi,
            timeout_seconds=timeout_seconds,
            email=email,
            fetch_json=fetch_json,
        )
    except Exception as exc:  # noqa: BLE001
        openalex_error = exc
        openalex_work = None

    if crossref_error is not None and openalex_error is not None:
        raise RuntimeError(
            f"Crossref and OpenAlex metadata lookups failed for DOI {doi}: "
            f"Crossref={crossref_error}; OpenAlex={openalex_error}"
        )

    # Crossref stays the first choice for bibliographic fields, while OpenAlex
    # fills only the gaps when Crossref is sparse.
    title = _first_nonempty(
        naming.normalize_title_text(
            crossref_message.get("title") if crossref_message is not None else None
        )
        or "",
        naming.normalize_title_text(
            openalex_work.get("title") if openalex_work is not None else None
        )
        or "",
    )
    abstract = _first_nonempty(
        extract_crossref_abstract(crossref_message),
        extract_openalex_abstract(openalex_work),
    )
    # Both author lists are flattened once and reused for the three
    # author-derived columns, instead of re-walking the payloads per column.
    crossref_authors = crossref_author_rows(crossref_message)
    openalex_authors = openalex_author_rows(openalex_work)

    authors = _first_nonempty(
        format_author_names(crossref_authors),
        format_author_names(openalex_authors),
    )
    orcid_ids = _first_nonempty(
        format_orcid_ids(crossref_authors),
        format_orcid_ids(openalex_authors),
    )
    affiliations = _first_nonempty(
        format_affiliations(crossref_authors),
        format_affiliations(openalex_authors),
    )
    published_date = _first_nonempty(
        crossref.extract_published_date(crossref_message),
        extract_openalex_published_date(openalex_work),
    )
    journal_title = _first_nonempty(
        extract_crossref_journal_title(crossref_message),
        extract_openalex_journal_title(openalex_work),
    )
    publisher = _first_nonempty(
        extract_crossref_publisher(crossref_message),
        extract_openalex_publisher(openalex_work),
    )
    crossref_subjects = extract_crossref_keywords(crossref_message)
    keywords = _first_nonempty(
        extract_openalex_keywords(openalex_work),
        crossref_subjects,
    )
    # Topics intentionally fall back to Crossref subjects, which is better than
    # leaving the column blank when OpenAlex has no topic list for a DOI.
    topics = _first_nonempty(
        extract_openalex_topics(openalex_work),
        crossref_subjects,
    )

    return MetadataRecord(
        doi=doi,
        title=title,
        abstract=abstract,
        authors=authors,
        orcid_ids=orcid_ids,
        affiliations=affiliations,
        published_date=published_date,
        journal_title=journal_title,
        publisher=publisher,
        keywords=keywords,
        topics=topics,
    )


def build_default_metadata_csv_path(
    dois_file_path: Path,
    metadata_dir: Path,
) -> Path:
    """Return the default CSV path inside the metadata output directory."""
    output_stem = strip_queue_file_suffix(dois_file_path)
    return metadata_dir / f"{output_stem}_metadata.csv"


def write_ready_metadata_records(
    writer: csv.DictWriter,
    csv_file: TextIO,
    pending_records: dict[int, MetadataRecord],
    next_row_index: int,
) -> int:
    """Write completed metadata rows while preserving input DOI order.

    Parameters
    ----------
    writer:
        CSV writer already configured with the metadata field names.
    csv_file:
        Open CSV stream that should be flushed after each row.
    pending_records:
        Mapping from one-based DOI input positions to completed records. A
        dictionary is used because parallel workers can finish out of order.
    next_row_index:
        One-based input position that should be written next.

    Returns
    -------
    int
        Next one-based input position still waiting to be written.
    """
    while next_row_index in pending_records:
        ready_record = pending_records.pop(next_row_index)
        writer.writerow(asdict(ready_record))
        csv_file.flush()
        next_row_index += 1

    return next_row_index


def export_metadata_from_dois(
    dois: list[str],
    output_csv_path: Path,
    email: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    fetch_json: JsonFetcher = fetch_json_payload,
    progress_stream: TextIO | None = sys.stderr,
    max_workers: int = DEFAULT_METADATA_MAX_WORKERS,
    request_delay_seconds: float = DEFAULT_REQUEST_DELAY_SECONDS,
) -> Path:
    """Fetch metadata for a DOI list and stream the CSV output.

    The exporter writes one row at a time so long journal runs produce a
    partially usable CSV immediately instead of only at the very end. It also
    writes per-DOI progress lines to the configured stream so network-bound
    batches do not appear to hang silently.

    `max_workers` controls bounded parallelism for the network-bound metadata
    lookups. Rows are still written in the original DOI order, so downstream
    CSV comparisons remain stable even when workers finish out of order.

    `request_delay_seconds` spaces request starts to the same provider host.
    This keeps long batches from sending a tight burst that is likely to trigger
    provider throttling after a fast initial phase.
    """
    output_csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(MetadataRecord.__annotations__.keys())
    total_dois = len(dois)
    worker_count = max(1, max_workers)
    paced_fetch_json = build_paced_json_fetcher(
        fetch_json=fetch_json,
        request_delay_seconds=request_delay_seconds,
    )

    if progress_stream is not None:
        print(
            f"Starting metadata export for {total_dois} DOI(s) "
            f"with {worker_count} worker(s), "
            f"{max(0.0, request_delay_seconds):.3f}s host delay "
            f"-> {output_csv_path}",
            file=progress_stream,
            flush=True,
        )

    with output_csv_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        csv_file.flush()

        pending_records: dict[int, MetadataRecord] = {}
        next_row_index = 1
        completed_count = 0

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_work_item: dict[Future[MetadataRecord], tuple[int, str]] = {}

            for input_index, doi in enumerate(dois, start=1):
                future = executor.submit(
                    build_metadata_record,
                    doi=doi,
                    email=email,
                    timeout_seconds=timeout_seconds,
                    fetch_json=paced_fetch_json,
                )
                future_to_work_item[future] = (input_index, doi)

            for future in as_completed(future_to_work_item):
                input_index, doi = future_to_work_item[future]
                completed_count += 1

                if progress_stream is not None:
                    percentage_complete = (
                        (completed_count / total_dois) * 100 if total_dois else 100.0
                    )
                    print(
                        f"[{completed_count}/{total_dois}] "
                        f"{percentage_complete:5.1f}% "
                        f"Exporting metadata for DOI {doi}",
                        file=progress_stream,
                        flush=True,
                    )

                try:
                    # Keep one row per DOI even if both providers fail.
                    record = future.result()
                except Exception as exc:  # noqa: BLE001
                    if progress_stream is not None:
                        print(
                            f"failed metadata for DOI {doi}: {exc}",
                            file=progress_stream,
                            flush=True,
                        )

                    # Keep one row per DOI even when both providers fail, so the
                    # output CSV stays aligned with the input worklist.
                    record = MetadataRecord(
                        doi=doi,
                        title="",
                        abstract="",
                        authors="",
                        orcid_ids="",
                        affiliations="",
                        published_date="",
                        journal_title="",
                        publisher="",
                        keywords="",
                        topics="",
                    )

                pending_records[input_index] = record
                next_row_index = write_ready_metadata_records(
                    writer=writer,
                    csv_file=csv_file,
                    pending_records=pending_records,
                    next_row_index=next_row_index,
                )

        # Every input position is buffered exactly once above, and the writer
        # drains each contiguous run as soon as its gap fills, so the buffer is
        # necessarily empty once the last future has been handled.
        assert not pending_records, (
            f"unwritten metadata rows: {sorted(pending_records)}"
        )

    return output_csv_path
