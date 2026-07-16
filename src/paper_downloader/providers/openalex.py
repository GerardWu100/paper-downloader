"""OpenAlex provider URL construction and JSON fetching."""

from __future__ import annotations

from urllib.parse import quote, urlencode

DEFAULT_HTTP_USER_AGENT: str = "paper-downloader/0.1.0"
OPENALEX_SOURCE_URL_TEMPLATE: str = "https://api.openalex.org/sources/issn:{issn}"
OPENALEX_WORKS_URL: str = "https://api.openalex.org/works"

JsonObject = dict[str, object]


def build_headers() -> dict[str, str]:
    """Build OpenAlex request headers."""
    return {"User-Agent": DEFAULT_HTTP_USER_AGENT}


def build_source_url(issn: str) -> str:
    """Build the OpenAlex source lookup URL for one ISSN."""
    return OPENALEX_SOURCE_URL_TEMPLATE.format(issn=issn)


def build_works_cursor_url(source_id: str, rows: int, cursor: str) -> str:
    """Build an OpenAlex works cursor-pagination URL for one source."""
    query_string = urlencode(
        {
            "filter": (
                f"primary_location.source.id:{source_id},type:article,has_doi:true"
            ),
            "per-page": str(rows),
            "cursor": cursor,
        }
    )
    return f"{OPENALEX_WORKS_URL}?{query_string}"


def build_work_url(doi: str) -> str:
    """Build the OpenAlex work URL for one DOI."""
    encoded_doi = quote(doi, safe="")
    return f"{OPENALEX_WORKS_URL}/https://doi.org/{encoded_doi}"
