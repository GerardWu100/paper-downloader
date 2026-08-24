"""ISSN-to-DOI collection helpers.

This module mirrors the useful metadata flow from `education-scraper`. For one
ISSN, it queries:

1. OpenAlex `sources/issn:<issn>` to resolve the journal source identifier.
2. OpenAlex `works` with cursor pagination for article DOIs.
3. Crossref `works` with cursor pagination for journal-article DOIs.

The final DOI list is normalized, de-duplicated, and sorted before being
written to disk.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ._http import JsonObject, extract_object_list
from ._http import fetch_json_payload as _core_fetch_json_payload
from .models import normalize_dois_preserving_order
from .providers import crossref, openalex

OPENALEX_MAX_PER_PAGE: int = 200
FIRST_CURSOR: str = "*"

JsonFetcher = Callable[[str, dict[str, str] | None], JsonObject]


def fetch_json_payload(
    url: str,
    headers: dict[str, str] | None = None,
) -> JsonObject:
    """Fetch one JSON payload from HTTP."""
    return _core_fetch_json_payload(url, headers=headers)


def _non_empty_string(raw_value: object) -> str | None:
    """Return the value when it is a non-empty string, otherwise `None`."""
    if not isinstance(raw_value, str) or not raw_value:
        return None

    return raw_value


def _collect_cursor_paginated_dois(
    fetch_page: Callable[[str], JsonObject],
    extract_page_dois: Callable[[JsonObject], list[str]],
    extract_next_cursor: Callable[[JsonObject], str | None],
) -> list[str]:
    """Collect raw DOI values from one cursor-paginated provider endpoint.

    Parameters
    ----------
    fetch_page:
        Called with a cursor token; returns that page's decoded JSON body.
    extract_page_dois:
        Pulls the DOI strings out of one page.
    extract_next_cursor:
        Returns the cursor for the following page, or ``None`` to stop. Each
        provider decides there whether the run is finished.

    Returns
    -------
    list[str]
        DOI strings exactly as the provider supplied them. Normalization is
        left to the caller so a merged multi-provider list is only cleaned once.
    """
    collected_dois: list[str] = []
    cursor: str | None = FIRST_CURSOR
    seen_cursors: set[str] = {FIRST_CURSOR}

    while cursor is not None:
        payload = fetch_page(cursor)
        collected_dois.extend(extract_page_dois(payload))
        cursor = extract_next_cursor(payload)

        # A repeated cursor means the provider is no longer advancing the page
        # token, so stop instead of looping forever.
        if cursor is not None:
            if cursor in seen_cursors:
                break

            seen_cursors.add(cursor)

    return collected_dois


def normalize_doi_list(raw_dois: list[str]) -> list[str]:
    """Normalize, de-duplicate, and sort DOI values."""
    return sorted(normalize_dois_preserving_order(raw_dois))


def fetch_openalex_source_id(
    issn: str,
    email: str | None = None,
    fetch_json: JsonFetcher = fetch_json_payload,
) -> str | None:
    """Resolve an OpenAlex source identifier from one ISSN.

    Parameters
    ----------
    issn:
        Journal ISSN to look up.
    email:
        Polite-pool contact address, or ``None`` to use the configured
        process-wide address.
    fetch_json:
        Injectable JSON fetcher.

    Returns
    -------
    str or None
        Bare OpenAlex source identifier, or ``None`` when the ISSN is unknown.
    """
    payload = fetch_json(
        openalex.build_source_url(issn, email),
        openalex.build_headers(email),
    )
    source_id = payload.get("id")

    if not isinstance(source_id, str):
        return None

    if not source_id:
        return None

    return source_id.rsplit("/", maxsplit=1)[-1]


def fetch_openalex_dois(
    issn: str,
    rows: int,
    email: str | None = None,
    fetch_json: JsonFetcher = fetch_json_payload,
) -> list[str]:
    """Collect DOI values for one ISSN from OpenAlex.

    Parameters
    ----------
    issn:
        Journal ISSN to collect works for.
    rows:
        Requested page size, clamped to ``OPENALEX_MAX_PER_PAGE``.
    email:
        Polite-pool contact address, or ``None`` to use the configured
        process-wide address.
    fetch_json:
        Injectable JSON fetcher.

    Returns
    -------
    list[str]
        Normalized, de-duplicated, sorted DOI strings.
    """
    source_id = fetch_openalex_source_id(
        issn=issn,
        email=email,
        fetch_json=fetch_json,
    )

    if source_id is None:
        return []

    per_page = min(rows, OPENALEX_MAX_PER_PAGE)

    def fetch_page(cursor: str) -> JsonObject:
        page_url = openalex.build_works_cursor_url(source_id, per_page, cursor, email)
        return fetch_json(page_url, openalex.build_headers(email))

    def extract_page_dois(payload: JsonObject) -> list[str]:
        return [
            raw_result["doi"]
            for raw_result in extract_object_list(payload, "results")
            if isinstance(raw_result.get("doi"), str)
        ]

    def extract_next_cursor(payload: JsonObject) -> str | None:
        # An empty page means the crawl is done regardless of what cursor the
        # API hands back.
        if not extract_object_list(payload, "results"):
            return None

        meta_object = payload.get("meta")

        if not isinstance(meta_object, dict):
            return None

        return _non_empty_string(meta_object.get("next_cursor"))

    return normalize_doi_list(
        _collect_cursor_paginated_dois(
            fetch_page,
            extract_page_dois,
            extract_next_cursor,
        )
    )


def fetch_crossref_dois(
    issn: str,
    email: str,
    rows: int,
    fetch_json: JsonFetcher = fetch_json_payload,
) -> list[str]:
    """Collect DOI values for one ISSN from Crossref.

    Parameters
    ----------
    issn:
        Journal ISSN to filter works by.
    email:
        Polite-pool contact address sent to Crossref.
    rows:
        Requested page size. Crossref caps this at
        ``crossref.CROSSREF_MAX_ROWS_PER_PAGE``, so the value is clamped here
        before use. Without the clamp, a larger request produces a capped page
        that looks short, and pagination stops after the first page with a
        silently truncated DOI list.

    Returns
    -------
    list[str]
        Normalized, de-duplicated, sorted DOI strings.
    """
    page_size = min(rows, crossref.CROSSREF_MAX_ROWS_PER_PAGE)

    def fetch_page(cursor: str) -> JsonObject:
        page_url = crossref.build_works_cursor_url(issn, page_size, cursor, email)
        return fetch_json(page_url, crossref.build_polite_headers(email))

    def extract_page_items(payload: JsonObject) -> list[JsonObject]:
        message_object = crossref.extract_message(payload)

        if message_object is None:
            return []

        return extract_object_list(message_object, "items")

    def extract_page_dois(payload: JsonObject) -> list[str]:
        return [
            raw_item["DOI"]
            for raw_item in extract_page_items(payload)
            if isinstance(raw_item.get("DOI"), str)
        ]

    def extract_next_cursor(payload: JsonObject) -> str | None:
        # Crossref keeps returning a cursor past the end of the result set, so
        # a short page is the reliable signal that the crawl is finished. The
        # comparison uses the clamped page size, because that is what Crossref
        # actually returns for a full page.
        if len(extract_page_items(payload)) < page_size:
            return None

        message_object = crossref.extract_message(payload)

        if message_object is None:
            return None

        return _non_empty_string(message_object.get("next-cursor"))

    return normalize_doi_list(
        _collect_cursor_paginated_dois(
            fetch_page,
            extract_page_dois,
            extract_next_cursor,
        )
    )


def fetch_all_dois_for_issn(
    issn: str,
    email: str,
    rows: int,
    fetch_json: JsonFetcher = fetch_json_payload,
) -> list[str]:
    """Collect and merge DOI values from OpenAlex and Crossref."""
    openalex_dois = fetch_openalex_dois(
        issn=issn,
        rows=rows,
        email=email,
        fetch_json=fetch_json,
    )
    crossref_dois = fetch_crossref_dois(
        issn=issn,
        email=email,
        rows=rows,
        fetch_json=fetch_json,
    )
    merged_dois = openalex_dois + crossref_dois
    return normalize_doi_list(merged_dois)


def write_doi_file(
    dois_dir: Path,
    issn: str,
    dois: list[str],
) -> Path:
    """Write one DOI queue file for an ISSN.

    Parameters
    ----------
    dois_dir:
        Output directory for DOI queue files.
    issn:
        Journal ISSN that labels the queue file.
    dois:
        DOI list to persist.

    Returns
    -------
    Path
        Written DOI file path.
    """
    normalized_dois = normalize_doi_list(dois)

    if not normalized_dois:
        raise ValueError(f"No DOIs found for ISSN {issn}")

    dois_dir.mkdir(parents=True, exist_ok=True)
    dois_file_path = dois_dir / f"{issn}_dois.txt"

    with dois_file_path.open("w", encoding="utf-8") as dois_file:
        for doi in normalized_dois:
            dois_file.write(f"{doi}\n")

    return dois_file_path
