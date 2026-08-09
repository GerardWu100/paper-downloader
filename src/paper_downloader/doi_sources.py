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

from ._http import fetch_json_payload as _core_fetch_json_payload
from .models import normalize_doi
from .providers import crossref, openalex

OPENALEX_MAX_PER_PAGE: int = 200

JsonObject = dict[str, object]
JsonFetcher = Callable[[str, dict[str, str] | None], JsonObject]


def fetch_json_payload(
    url: str,
    headers: dict[str, str] | None = None,
) -> JsonObject:
    """Fetch one JSON payload from HTTP."""
    return _core_fetch_json_payload(url, headers=headers)


def _collect_cursor_paginated_dois(
    *,
    initial_cursor: str,
    build_page_url: Callable[[str], str],
    fetch_page: Callable[[str], JsonObject],
    extract_page_dois: Callable[[JsonObject], list[str]],
    page_has_more: Callable[[JsonObject], bool],
    next_cursor_from_page: Callable[[JsonObject], str | None],
) -> list[str]:
    """Collect DOI values from one cursor-paginated provider endpoint."""
    collected_dois: list[str] = []
    cursor = initial_cursor
    seen_cursors: set[str] = {cursor}

    while True:
        payload = fetch_page(build_page_url(cursor))
        collected_dois.extend(extract_page_dois(payload))

        if not page_has_more(payload):
            break

        next_cursor = next_cursor_from_page(payload)

        if not isinstance(next_cursor, str) or not next_cursor:
            break

        # Repeated cursors mean the provider is no longer advancing the page
        # token, so stop instead of looping forever.
        if next_cursor in seen_cursors:
            break

        seen_cursors.add(next_cursor)
        cursor = next_cursor

    return normalize_doi_list(collected_dois)


def normalize_doi_list(raw_dois: list[str]) -> list[str]:
    """Normalize, de-duplicate, and sort DOI values."""
    normalized_dois: set[str] = set()

    for raw_doi in raw_dois:
        candidate_doi = normalize_doi(raw_doi)

        # Blank lines and empty metadata values do not represent real work.
        if not candidate_doi:
            continue

        normalized_dois.add(candidate_doi)

    return sorted(normalized_dois)


def fetch_openalex_source_id(
    issn: str,
    fetch_json: JsonFetcher = fetch_json_payload,
) -> str | None:
    """Resolve an OpenAlex source identifier from one ISSN."""
    payload = fetch_json(openalex.build_source_url(issn), openalex.build_headers())
    source_id = payload.get("id")

    if not isinstance(source_id, str):
        return None

    if not source_id:
        return None

    return source_id.rsplit("/", maxsplit=1)[-1]


def fetch_openalex_dois(
    issn: str,
    rows: int,
    fetch_json: JsonFetcher = fetch_json_payload,
) -> list[str]:
    """Collect DOI values for one ISSN from OpenAlex."""
    source_id = fetch_openalex_source_id(issn=issn, fetch_json=fetch_json)

    if source_id is None:
        return []

    per_page = min(rows, OPENALEX_MAX_PER_PAGE)

    def build_page_url(cursor: str) -> str:
        return openalex.build_works_cursor_url(source_id, per_page, cursor)

    def fetch_page(url: str) -> JsonObject:
        return fetch_json(url, openalex.build_headers())

    def extract_page_dois(payload: JsonObject) -> list[str]:
        raw_results = payload.get("results")

        if not isinstance(raw_results, list):
            return []

        page_dois: list[str] = []

        for raw_result in raw_results:
            if not isinstance(raw_result, dict):
                continue

            raw_doi = raw_result.get("doi")

            if isinstance(raw_doi, str):
                page_dois.append(raw_doi)

        return page_dois

    def page_has_more(payload: JsonObject) -> bool:
        raw_results = payload.get("results")

        if not isinstance(raw_results, list) or not raw_results:
            return False

        meta_object = payload.get("meta")

        if not isinstance(meta_object, dict):
            return False

        next_cursor = meta_object.get("next_cursor")
        return isinstance(next_cursor, str) and bool(next_cursor)

    def next_cursor_from_page(payload: JsonObject) -> str | None:
        meta_object = payload.get("meta")

        if not isinstance(meta_object, dict):
            return None

        next_cursor = meta_object.get("next_cursor")

        if not isinstance(next_cursor, str) or not next_cursor:
            return None

        return next_cursor

    return _collect_cursor_paginated_dois(
        initial_cursor="*",
        build_page_url=build_page_url,
        fetch_page=fetch_page,
        extract_page_dois=extract_page_dois,
        page_has_more=page_has_more,
        next_cursor_from_page=next_cursor_from_page,
    )


def fetch_crossref_dois(
    issn: str,
    email: str,
    rows: int,
    fetch_json: JsonFetcher = fetch_json_payload,
) -> list[str]:
    """Collect DOI values for one ISSN from Crossref."""

    def build_page_url(cursor: str) -> str:
        return crossref.build_works_cursor_url(issn, rows, cursor, email)

    def fetch_page(url: str) -> JsonObject:
        return fetch_json(url, crossref.build_polite_headers(email))

    def extract_page_dois(payload: JsonObject) -> list[str]:
        message_object = payload.get("message")

        if not isinstance(message_object, dict):
            return []

        raw_items = message_object.get("items")

        if not isinstance(raw_items, list):
            return []

        page_dois: list[str] = []

        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue

            raw_doi = raw_item.get("DOI")

            if isinstance(raw_doi, str):
                page_dois.append(raw_doi)

        return page_dois

    def page_has_more(payload: JsonObject) -> bool:
        message_object = payload.get("message")

        if not isinstance(message_object, dict):
            return False

        raw_items = message_object.get("items")

        if not isinstance(raw_items, list) or len(raw_items) < rows:
            return False

        next_cursor = message_object.get("next-cursor")
        return isinstance(next_cursor, str) and bool(next_cursor)

    def next_cursor_from_page(payload: JsonObject) -> str | None:
        message_object = payload.get("message")

        if not isinstance(message_object, dict):
            return None

        next_cursor = message_object.get("next-cursor")

        if not isinstance(next_cursor, str) or not next_cursor:
            return None

        return next_cursor

    return _collect_cursor_paginated_dois(
        initial_cursor="*",
        build_page_url=build_page_url,
        fetch_page=fetch_page,
        extract_page_dois=extract_page_dois,
        page_has_more=page_has_more,
        next_cursor_from_page=next_cursor_from_page,
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
