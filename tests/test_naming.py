"""Tests for filename and metadata helpers."""

from __future__ import annotations

from pathlib import Path

from paper_downloader import naming


def setup_function() -> None:
    """Clear the DOI metadata cache before each test."""
    naming.lookup_doi_metadata.cache_clear()


def test_sanitize_doi_for_filename_keeps_ordinary_dois_readable() -> None:
    """An ordinary DOI should escape only its slash."""
    assert (
        naming.sanitize_doi_for_filename("10.1111/mafi.12108") == "10.1111__mafi.12108"
    )


def test_sanitize_doi_for_filename_replaces_characters_a_filesystem_rejects() -> None:
    """A colon should not survive into the filename."""
    marker = naming.sanitize_doi_for_filename("10.1111/mafi:12108")

    assert ":" not in marker
    assert marker.startswith("10.1111__mafi_12108")


def test_sanitize_doi_for_filename_separates_dois_that_escape_alike() -> None:
    """Two DOIs whose plain escape matches must get different markers.

    Both pairs below escape to the same text under a plain substitution: the
    first because a colon and an underscore both become an underscore, the
    second because a slash and a literal double underscore both become ``__``.
    A shared marker would make resume treat one DOI as already downloaded.
    """
    colliding_doi_pairs = [
        ("10.1111/mafi:12108", "10.1111/mafi_12108"),
        ("10.1575/1912/2489", "10.1575/1912__2489"),
    ]

    for first_doi, second_doi in colliding_doi_pairs:
        first_marker = naming.sanitize_doi_for_filename(first_doi)
        second_marker = naming.sanitize_doi_for_filename(second_doi)

        assert first_marker != second_marker


def test_sanitize_doi_for_filename_is_stable_across_calls() -> None:
    """Markers must be deterministic, or resume would miss its own files."""
    disambiguated_doi = "10.1111/mafi:12108"

    assert naming.sanitize_doi_for_filename(
        disambiguated_doi
    ) == naming.sanitize_doi_for_filename(disambiguated_doi)


def test_sanitize_title_for_filename_normalizes_text() -> None:
    """Title sanitization should remove invalid path characters."""
    sanitized_title = naming.sanitize_title_for_filename(
        "Speculating: gains/losses? <A test>"
    )

    assert sanitized_title == "Speculating gains losses A test"


def test_lookup_doi_metadata_falls_back_to_openalex(monkeypatch) -> None:
    """OpenAlex should supply metadata when Crossref does not."""
    monkeypatch.setattr(
        naming,
        "fetch_crossref_metadata",
        lambda doi: (None, None),
    )
    monkeypatch.setattr(
        naming,
        "fetch_openalex_metadata",
        lambda doi: ("Fallback Title", "2020"),
    )

    title, year = naming.lookup_doi_metadata("10.1/example")

    assert title == "Fallback Title"
    assert year == "2020"


def test_lookup_doi_metadata_merges_crossref_title_with_openalex_year(
    monkeypatch,
) -> None:
    """Missing Crossref year should fall back to OpenAlex year."""
    monkeypatch.setattr(
        naming,
        "fetch_crossref_metadata",
        lambda doi: ("Crossref Title", None),
    )
    monkeypatch.setattr(
        naming,
        "fetch_openalex_metadata",
        lambda doi: ("OpenAlex Title", "2024"),
    )

    title, year = naming.lookup_doi_metadata("10.1/example")

    assert title == "Crossref Title"
    assert year == "2024"


def test_lookup_doi_metadata_skips_openalex_when_crossref_is_complete(
    monkeypatch,
) -> None:
    """A complete Crossref result should avoid the OpenAlex fallback request."""
    openalex_call_count = 0

    monkeypatch.setattr(
        naming,
        "fetch_crossref_metadata",
        lambda doi: ("Crossref Title", "2024"),
    )

    def fetch_openalex_metadata(doi: str) -> tuple[str | None, str | None]:
        nonlocal openalex_call_count
        openalex_call_count += 1
        return "OpenAlex Title", "2024"

    monkeypatch.setattr(
        naming,
        "fetch_openalex_metadata",
        fetch_openalex_metadata,
    )

    title, year = naming.lookup_doi_metadata("10.1/example")

    assert title == "Crossref Title"
    assert year == "2024"
    assert openalex_call_count == 0


def test_fetch_crossref_metadata_uses_issued_year_when_published_missing() -> None:
    """Crossref `issued` should provide year when `published` is absent."""
    payload = {
        "message": {
            "title": ["Issued Date Article"],
            "issued": {"date-parts": [[2020, 5, 1]]},
        }
    }

    title, year = naming.fetch_crossref_metadata(
        "10.1/example",
        fetch_json=lambda url: payload,
    )

    assert title == "Issued Date Article"
    assert year == "2020"


def test_build_and_extract_doi_marker_round_trip() -> None:
    """Saved filename markers should round-trip through the parser."""
    filename = naming.build_target_pdf_filename("paper.pdf", "10.1111/mafi.12108")
    suffix = naming.extract_doi_resume_suffix_from_filename(Path(filename))

    assert filename == "paper__doi_10.1111__mafi.12108.pdf"
    assert suffix == "10.1111__mafi.12108"
