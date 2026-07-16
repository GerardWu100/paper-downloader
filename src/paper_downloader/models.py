"""Shared domain models and normalization helpers.

This module owns DOI identity rules used across provider collection, queue
files, ledgers, and saved-PDF filename markers.
"""

from __future__ import annotations

import re

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
