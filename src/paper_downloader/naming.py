"""Filename and DOI metadata helpers.

This module handles two related jobs:

1. Query DOI metadata from Crossref first and OpenAlex second.
2. Convert titles and DOIs into filesystem-safe filenames with a stable DOI
   marker for resume detection.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Callable

from ._http import fetch_json_payload as _core_fetch_json_payload
from .models import normalize_doi
from .providers import crossref, openalex

DOI_FILENAME_MARKER: str = "__doi_"
DOI_METADATA_CACHE_SIZE: int = 4096
REQUEST_TIMEOUT_SECONDS: int = 60
DOI_METADATA_USER_AGENT: str = "paper-downloader/0.1.0"
TITLE_FILENAME_MAX_STEM_LENGTH: int = 160
PDF_MAGIC_PREFIX: bytes = b"%PDF-"
PDF_MIN_VALID_SIZE_BYTES: int = 64
INVALID_FILENAME_CHARACTERS_PATTERN = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
GENERIC_PDF_FILENAME_NORMALIZER = re.compile(r"[\s_-]+")
GENERIC_PDF_FILENAME_STEMS: frozenset[str] = frozenset(
    {
        "article",
        "content",
        "default",
        "document",
        "download",
        "file",
        "full text",
        "fulltext",
        "main",
        "paper",
        "pdf",
    }
)
GENERIC_PDF_FILENAME_TOKENS: frozenset[str] = frozenset(
    {
        "article",
        "content",
        "default",
        "document",
        "download",
        "file",
        "full",
        "main",
        "paper",
        "pdf",
        "text",
    }
)
WHITESPACE_NORMALIZER = re.compile(r"\s+")

JsonObject = dict[str, object]
JsonFetcher = Callable[[str], JsonObject]


def fetch_json_payload(url: str) -> JsonObject:
    """Fetch one JSON object from a metadata endpoint."""
    return _core_fetch_json_payload(
        url,
        headers={"User-Agent": DOI_METADATA_USER_AGENT},
        timeout_seconds=REQUEST_TIMEOUT_SECONDS,
    )


def sanitize_doi_for_filename(doi: str) -> str:
    """Convert one DOI into a filesystem-safe marker fragment."""
    normalized_doi = normalize_doi(doi)
    return normalized_doi.replace("/", "__").replace(":", "_")


def normalize_title_text(raw_title: object) -> str | None:
    """Extract one normalized title string from a metadata payload."""
    if isinstance(raw_title, list):
        for raw_candidate in raw_title:
            normalized_candidate = normalize_title_text(raw_candidate)

            if normalized_candidate is not None:
                return normalized_candidate

        return None

    if not isinstance(raw_title, str):
        return None

    normalized_title = " ".join(raw_title.split())

    if not normalized_title:
        return None

    return normalized_title


def fetch_crossref_message(
    doi: str,
    fetch_json: Callable[[str], JsonObject] = fetch_json_payload,
) -> JsonObject | None:
    """Fetch the Crossref `message` object for one DOI."""
    payload = fetch_json(crossref.build_work_url(doi))
    message_object = payload.get("message")

    if not isinstance(message_object, dict):
        return None

    return message_object


def fetch_crossref_metadata(
    doi: str,
    fetch_json: Callable[[str], JsonObject] = fetch_json_payload,
) -> tuple[str | None, str | None]:
    """Fetch title and year metadata for one DOI from Crossref."""
    message_object = fetch_crossref_message(doi=doi, fetch_json=fetch_json)

    if message_object is None:
        return None, None

    title = normalize_title_text(message_object.get("title"))
    year: str | None = None

    for date_key in ("published", "published-online", "published-print", "issued"):
        date_object = message_object.get(date_key)

        if not isinstance(date_object, dict):
            continue

        raw_date_parts = date_object.get("date-parts")

        if not isinstance(raw_date_parts, list) or not raw_date_parts:
            continue

        first_date_part = raw_date_parts[0]

        if not isinstance(first_date_part, list) or not first_date_part:
            continue

        raw_year = first_date_part[0]

        if not isinstance(raw_year, int):
            continue

        year = str(raw_year)
        break

    return title, year


def fetch_openalex_metadata(
    doi: str,
    fetch_json: Callable[[str], JsonObject] = fetch_json_payload,
) -> tuple[str | None, str | None]:
    """Fetch title and year metadata for one DOI from OpenAlex."""
    payload = fetch_json(openalex.build_work_url(doi))
    title = normalize_title_text(payload.get("title"))
    raw_year = payload.get("publication_year")
    year = str(raw_year) if isinstance(raw_year, int) else None
    return title, year


@lru_cache(maxsize=DOI_METADATA_CACHE_SIZE)
def lookup_doi_metadata(doi: str) -> tuple[str | None, str | None]:
    """Resolve title and year metadata for one DOI.

    Crossref is queried first because it tends to provide stable publisher-side
    metadata. OpenAlex is used as the fallback source only when Crossref is
    missing the title or year, which avoids a wasted second metadata request
    for the common complete-Crossref case.
    """
    crossref_title, crossref_year = fetch_crossref_metadata(doi)

    if crossref_title is not None and crossref_year is not None:
        return crossref_title, crossref_year

    openalex_title, openalex_year = fetch_openalex_metadata(doi)

    merged_title = crossref_title if crossref_title is not None else openalex_title
    merged_year = crossref_year if crossref_year is not None else openalex_year
    return merged_title, merged_year


def sanitize_title_for_filename(title: str) -> str | None:
    """Convert one article title into a readable ASCII filename stem."""
    ascii_title = (
        unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    )
    cleaned_title = INVALID_FILENAME_CHARACTERS_PATTERN.sub(" ", ascii_title)
    cleaned_title = WHITESPACE_NORMALIZER.sub(" ", cleaned_title)
    cleaned_title = cleaned_title.strip()
    cleaned_title = cleaned_title.strip(".")

    if not cleaned_title:
        return None

    if len(cleaned_title) > TITLE_FILENAME_MAX_STEM_LENGTH:
        cleaned_title = cleaned_title[:TITLE_FILENAME_MAX_STEM_LENGTH]
        cleaned_title = cleaned_title.rstrip(" .")

    if not cleaned_title:
        return None

    return cleaned_title


def normalize_filename_stem(base_filename: str) -> str:
    """Normalize one filename stem for generic-name checks."""
    stem = Path(base_filename).stem.strip().lower()
    normalized_stem = GENERIC_PDF_FILENAME_NORMALIZER.sub(" ", stem)
    return normalized_stem.strip()


def filename_looks_generic(base_filename: str) -> bool:
    """Return `True` when the filename is too generic to preserve."""
    normalized_stem = normalize_filename_stem(base_filename)

    if not normalized_stem:
        return True

    if normalized_stem in GENERIC_PDF_FILENAME_STEMS:
        return True

    normalized_tokens = tuple(token for token in normalized_stem.split(" ") if token)

    if not normalized_tokens:
        return True

    if all(token.isdigit() for token in normalized_tokens):
        return True

    if all(token in GENERIC_PDF_FILENAME_TOKENS for token in normalized_tokens):
        return True

    return False


def resolve_pdf_base_filename(base_filename: str, doi: str) -> str:
    """Prefer DOI metadata title over the raw server filename.

    Parameters
    ----------
    base_filename:
        Filename suggested by HTTP headers or URL parsing.
    doi:
        DOI used to fetch metadata title candidates.

    Returns
    -------
    str
        Metadata title filename when available, otherwise the original
        ``base_filename``.
    """
    title, _ = lookup_doi_metadata(doi)

    if title is not None:
        title_stem = sanitize_title_for_filename(title)

        if title_stem is not None:
            return f"{title_stem}.pdf"

    return base_filename


def build_target_pdf_filename(base_filename: str, doi: str) -> str:
    """Build the final saved PDF filename for one DOI."""
    suggested_path = Path(base_filename)
    filename_stem = suggested_path.stem
    filename_suffix = suggested_path.suffix or ".pdf"
    doi_resume_suffix = sanitize_doi_for_filename(doi)
    return f"{filename_stem}{DOI_FILENAME_MARKER}{doi_resume_suffix}{filename_suffix}"


def extract_doi_resume_suffix_from_filename(pdf_path: Path) -> str | None:
    """Extract the DOI marker fragment from one saved PDF path."""
    marker_position = pdf_path.stem.rfind(DOI_FILENAME_MARKER)

    if marker_position == -1:
        return None

    return pdf_path.stem[marker_position + len(DOI_FILENAME_MARKER) :].lower()


def pdf_file_bytes_look_valid(pdf_path: Path) -> bool:
    """Return `True` when an existing file appears to be a real PDF.

    Parameters
    ----------
    pdf_path:
        Candidate ``*.pdf`` path found during resume scanning.

    Returns
    -------
    bool
        ``True`` only when the file is large enough to be plausible and starts
        with the standard ``%PDF-`` magic bytes.
    """
    try:
        if pdf_path.stat().st_size < PDF_MIN_VALID_SIZE_BYTES:
            return False

        with pdf_path.open("rb") as pdf_file:
            file_prefix = pdf_file.read(len(PDF_MAGIC_PREFIX))
    except OSError:
        return False

    return file_prefix == PDF_MAGIC_PREFIX


def collect_completed_doi_suffixes(output_root_dir: Path) -> set[str]:
    """Collect DOI marker fragments from every saved PDF below one root."""
    completed_suffixes: set[str] = set()

    if not output_root_dir.exists():
        return completed_suffixes

    for pdf_path in output_root_dir.rglob("*.pdf"):
        doi_resume_suffix = extract_doi_resume_suffix_from_filename(pdf_path)

        if doi_resume_suffix is None:
            continue

        if not pdf_file_bytes_look_valid(pdf_path):
            continue

        completed_suffixes.add(doi_resume_suffix)

    return completed_suffixes
