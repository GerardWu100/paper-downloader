"""Crossref provider URL construction and JSON fetching."""

from __future__ import annotations

from urllib.parse import quote, urlencode

from paper_downloader._http import fetch_json_payload as _core_fetch_json_payload

DEFAULT_HTTP_USER_AGENT: str = "paper-downloader/0.1.0"
CROSSREF_WORKS_URL: str = "https://api.crossref.org/works"

JsonObject = dict[str, object]


def build_polite_headers(email: str) -> dict[str, str]:
    """Build Crossref polite-pool headers for one email address."""
    return {"User-Agent": f"{DEFAULT_HTTP_USER_AGENT} (mailto:{email})"}


def fetch_timed_json_payload(
    url: str,
    headers: dict[str, str] | None,
    timeout_seconds: int,
) -> JsonObject:
    """Fetch one Crossref JSON payload with an explicit timeout."""
    return _core_fetch_json_payload(
        url,
        headers=headers,
        timeout_seconds=timeout_seconds,
    )


def build_works_cursor_url(issn: str, rows: int, cursor: str, email: str) -> str:
    """Build a Crossref cursor-pagination URL for one ISSN."""
    query_string = urlencode(
        {
            "filter": f"issn:{issn},type:journal-article",
            "select": "DOI",
            "rows": str(rows),
            "cursor": cursor,
            "mailto": email,
        }
    )
    return f"{CROSSREF_WORKS_URL}?{query_string}"


def build_work_url(doi: str) -> str:
    """Build the Crossref work URL for one DOI."""
    encoded_doi = quote(doi, safe="")
    return f"{CROSSREF_WORKS_URL}/{encoded_doi}"
