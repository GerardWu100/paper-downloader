"""Shared domain models and normalization helpers.

This module owns DOI identity rules used across provider collection, queue
files, ledgers, and saved-PDF filename markers.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

DOI_URL_PREFIX_PATTERN = re.compile(r"^https?://(?:dx\.)?doi\.org/", re.IGNORECASE)


def normalize_doi(raw_doi: str) -> str:
    """Return the canonical DOI identity string.

    Parameters
    ----------
    raw_doi:
        DOI text from a provider, queue file, ledger row, command-line
        argument, or DOI URL. URL prefixes are accepted.

    Returns
    -------
    str
        DOI without a DOI URL prefix, stripped of surrounding whitespace, and
        lowercased because DOI identity is case-insensitive.
    """
    stripped_doi = raw_doi.strip()
    doi_without_url_prefix = DOI_URL_PREFIX_PATTERN.sub("", stripped_doi)
    return doi_without_url_prefix.lower()


def normalize_dois_preserving_order(raw_dois: Iterable[str]) -> list[str]:
    """Normalize a DOI collection, drop blanks, and de-duplicate.

    First-seen order is preserved so callers that care about queue order (the
    download worklist) and callers that do not (ledger comparison sets) can
    share one implementation. Sort the result when a stable on-disk order is
    wanted.

    Parameters
    ----------
    raw_dois:
        DOI strings from any source: provider payloads, queue files, ledger
        rows, or command-line arguments.

    Returns
    -------
    list[str]
        Canonical DOI strings, without blanks or repeats, in first-seen order.
    """
    normalized_dois: list[str] = []
    seen_dois: set[str] = set()

    for raw_doi in raw_dois:
        normalized_doi = normalize_doi(raw_doi)

        # Blank lines and empty metadata values do not represent real work.
        if not normalized_doi or normalized_doi in seen_dois:
            continue

        seen_dois.add(normalized_doi)
        normalized_dois.append(normalized_doi)

    return normalized_dois
