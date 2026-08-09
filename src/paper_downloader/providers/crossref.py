"""Crossref URL construction and payload parsing.

Everything that knows the shape of a Crossref response lives here: the polite
pool headers, the works endpoints, the `message` envelope, and the date field
ordering. Callers pass payloads in and get plain Python values back.
"""

from __future__ import annotations

from urllib.parse import quote, urlencode

from .._http import DEFAULT_HTTP_USER_AGENT, JsonObject

CROSSREF_WORKS_URL: str = "https://api.crossref.org/works"

# Crossref exposes the publication date under several keys. The generic
# `published` field is the most reliable, so it is tried first and the more
# specific variants act as fallbacks.
PUBLICATION_DATE_KEYS: tuple[str, ...] = (
    "published",
    "published-online",
    "published-print",
    "issued",
)
MAX_DATE_PARTS: int = 3

__all__ = [
    "CROSSREF_WORKS_URL",
    "MAX_DATE_PARTS",
    "PUBLICATION_DATE_KEYS",
    "build_polite_headers",
    "build_work_url",
    "build_works_cursor_url",
    "extract_message",
    "extract_published_date",
]


def build_polite_headers(email: str) -> dict[str, str]:
    """Build Crossref polite-pool headers for one email address."""
    return {"User-Agent": f"{DEFAULT_HTTP_USER_AGENT} (mailto:{email})"}


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


def extract_message(payload: JsonObject) -> JsonObject | None:
    """Unwrap the `message` object that Crossref nests every work inside.

    Parameters
    ----------
    payload:
        Decoded JSON body of a Crossref works response.

    Returns
    -------
    dict[str, object] or None
        The `message` object, or ``None`` when the envelope is missing or is
        not an object.
    """
    message_object = payload.get("message")

    if not isinstance(message_object, dict):
        return None

    return message_object


def extract_published_date(message_object: JsonObject | None) -> str:
    """Return the best available Crossref publication date string.

    Crossref stores dates as `{"date-parts": [[year, month, day]]}`, where the
    month and day are optional. The parts are zero-padded and joined with
    hyphens, so the result is one of ``""``, ``"2024"``, ``"2024-01"``, or
    ``"2024-01-15"``.

    Parameters
    ----------
    message_object:
        Crossref `message` object, or ``None`` when the fetch failed.

    Returns
    -------
    str
        Date string as described above. Empty when no usable date is present.
    """
    if message_object is None:
        return ""

    for date_key in PUBLICATION_DATE_KEYS:
        raw_date_object = message_object.get(date_key)

        if not isinstance(raw_date_object, dict):
            continue

        raw_date_parts = raw_date_object.get("date-parts")

        if not isinstance(raw_date_parts, list) or not raw_date_parts:
            continue

        first_date_part = raw_date_parts[0]

        if not isinstance(first_date_part, list) or not first_date_part:
            continue

        normalized_parts: list[str] = []

        # The year is four digits; month and day are two. Stop at the first
        # non-integer part so a malformed tail cannot corrupt the prefix.
        for raw_part in first_date_part[:MAX_DATE_PARTS]:
            if not isinstance(raw_part, int):
                break

            if not normalized_parts:
                normalized_parts.append(f"{raw_part:04d}")
                continue

            normalized_parts.append(f"{raw_part:02d}")

        if normalized_parts:
            return "-".join(normalized_parts)

    return ""
