"""OpenAlex provider URL construction and JSON fetching."""

from __future__ import annotations

from urllib.parse import quote, urlencode

from .._http import DEFAULT_HTTP_USER_AGENT, polite_pool_email

OPENALEX_SOURCE_URL_TEMPLATE: str = "https://api.openalex.org/sources/issn:{issn}"
OPENALEX_WORKS_URL: str = "https://api.openalex.org/works"

# OpenAlex asks callers to identify themselves with a contact address, which
# routes them to the faster and more forgiving polite pool. The address is
# operator-supplied, so every helper here degrades to an anonymous request when
# none is configured.
OPENALEX_MAILTO_QUERY_FIELD: str = "mailto"


def resolve_contact_email(email: str | None = None) -> str:
    """Return the contact address to send to OpenAlex.

    Parameters
    ----------
    email:
        Explicit contact address, or ``None`` to fall back to the process-wide
        value set from configuration.

    Returns
    -------
    str
        Trimmed contact address, or an empty string when none is configured.
    """
    if email is None:
        return polite_pool_email()

    return email.strip()


def build_headers(email: str | None = None) -> dict[str, str]:
    """Build OpenAlex request headers, adding a contact address when known."""
    contact_email = resolve_contact_email(email)

    if not contact_email:
        return {"User-Agent": DEFAULT_HTTP_USER_AGENT}

    return {"User-Agent": f"{DEFAULT_HTTP_USER_AGENT} (mailto:{contact_email})"}


def _build_polite_query_fields(email: str | None) -> dict[str, str]:
    """Return the `mailto` query field, or nothing when no address is set."""
    contact_email = resolve_contact_email(email)

    if not contact_email:
        return {}

    return {OPENALEX_MAILTO_QUERY_FIELD: contact_email}


def build_source_url(issn: str, email: str | None = None) -> str:
    """Build the OpenAlex source lookup URL for one ISSN."""
    base_url = OPENALEX_SOURCE_URL_TEMPLATE.format(issn=issn)
    polite_query_fields = _build_polite_query_fields(email)

    if not polite_query_fields:
        return base_url

    return f"{base_url}?{urlencode(polite_query_fields)}"


def build_works_cursor_url(
    source_id: str,
    rows: int,
    cursor: str,
    email: str | None = None,
) -> str:
    """Build an OpenAlex works cursor-pagination URL for one source."""
    query_fields = {
        "filter": (f"primary_location.source.id:{source_id},type:article,has_doi:true"),
        "per-page": str(rows),
        "cursor": cursor,
    }
    query_fields.update(_build_polite_query_fields(email))
    return f"{OPENALEX_WORKS_URL}?{urlencode(query_fields)}"


def build_work_url(doi: str, email: str | None = None) -> str:
    """Build the OpenAlex work URL for one DOI."""
    encoded_doi = quote(doi, safe="")
    work_url = f"{OPENALEX_WORKS_URL}/https://doi.org/{encoded_doi}"
    polite_query_fields = _build_polite_query_fields(email)

    if not polite_query_fields:
        return work_url

    return f"{work_url}?{urlencode(polite_query_fields)}"
