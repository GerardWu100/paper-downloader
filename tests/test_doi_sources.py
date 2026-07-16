"""Tests for ISSN-to-DOI collection."""

from __future__ import annotations

from pathlib import Path

from paper_downloader import doi_sources


def test_normalize_doi_list_strips_urls_and_sorts() -> None:
    """DOI normalization should strip prefixes and sort unique values."""
    normalized_dois = doi_sources.normalize_doi_list(
        [
            "https://doi.org/10.2/bar",
            "10.1/foo",
            "http://dx.doi.org/10.2/bar",
            "  ",
        ]
    )

    assert normalized_dois == ["10.1/foo", "10.2/bar"]


def test_normalize_doi_list_lowercases_for_identity() -> None:
    """DOI identity should be case-insensitive across raw and URL inputs."""
    normalized_dois = doi_sources.normalize_doi_list(
        [
            "https://doi.org/10.1000/ABC",
            "10.1000/abc",
        ]
    )

    assert normalized_dois == ["10.1000/abc"]


def test_fetch_openalex_dois_paginates_results() -> None:
    """OpenAlex DOI collection should follow `next_cursor`."""

    def fake_fetch(url: str, headers: dict[str, str] | None) -> dict[str, object]:
        if "sources/issn:" in url:
            return {"id": "https://openalex.org/S123"}

        if "cursor=%2A" in url:
            return {
                "results": [{"doi": "https://doi.org/10.1/foo"}],
                "meta": {"next_cursor": "next-page"},
            }

        if "cursor=next-page" in url:
            return {
                "results": [{"doi": "10.2/bar"}],
                "meta": {"next_cursor": ""},
            }

        raise AssertionError(f"Unexpected URL: {url}")

    dois = doi_sources.fetch_openalex_dois(
        issn="1467-9965",
        rows=1000,
        fetch_json=fake_fetch,
    )

    assert dois == ["10.1/foo", "10.2/bar"]


def test_fetch_crossref_dois_paginates_results() -> None:
    """Crossref DOI collection should use cursor pagination."""

    def fake_fetch(url: str, headers: dict[str, str] | None) -> dict[str, object]:
        if "cursor=%2A" in url:
            return {
                "message": {
                    "items": [{"DOI": "10.3/baz"}, {"DOI": "10.4/qux"}],
                    "next-cursor": "next-crossref",
                }
            }

        if "cursor=next-crossref" in url:
            return {
                "message": {
                    "items": [{"DOI": "10.5/quux"}],
                    "next-cursor": "",
                }
            }

        raise AssertionError(f"Unexpected URL: {url}")

    dois = doi_sources.fetch_crossref_dois(
        issn="1467-9965",
        email="you@example.com",
        rows=2,
        fetch_json=fake_fetch,
    )

    assert dois == ["10.3/baz", "10.4/qux", "10.5/quux"]


def test_fetch_openalex_dois_stops_when_cursor_repeats() -> None:
    """OpenAlex pagination should stop if the API repeats one cursor."""
    fetch_call_count = 0

    def fake_fetch(url: str, headers: dict[str, str] | None) -> dict[str, object]:
        nonlocal fetch_call_count

        if "sources/issn:" in url:
            return {"id": "https://openalex.org/S123"}

        fetch_call_count += 1

        if "cursor=%2A" in url:
            return {
                "results": [{"doi": "10.1/foo"}],
                "meta": {"next_cursor": "repeat-cursor"},
            }

        if "cursor=repeat-cursor" in url:
            return {
                "results": [{"doi": "10.2/bar"}],
                "meta": {"next_cursor": "repeat-cursor"},
            }

        raise AssertionError(f"Unexpected URL: {url}")

    dois = doi_sources.fetch_openalex_dois(
        issn="1467-9965",
        rows=1000,
        fetch_json=fake_fetch,
    )

    assert dois == ["10.1/foo", "10.2/bar"]
    assert fetch_call_count == 2


def test_fetch_crossref_dois_stops_when_cursor_repeats() -> None:
    """Crossref pagination should stop if the API repeats one cursor."""
    fetch_call_count = 0

    def fake_fetch(url: str, headers: dict[str, str] | None) -> dict[str, object]:
        nonlocal fetch_call_count
        fetch_call_count += 1

        if "cursor=%2A" in url:
            return {
                "message": {
                    "items": [{"DOI": "10.3/baz"}],
                    "next-cursor": "repeat-crossref",
                }
            }

        if "cursor=repeat-crossref" in url:
            return {
                "message": {
                    "items": [{"DOI": "10.4/qux"}],
                    "next-cursor": "repeat-crossref",
                }
            }

        raise AssertionError(f"Unexpected URL: {url}")

    dois = doi_sources.fetch_crossref_dois(
        issn="1467-9965",
        email="you@example.com",
        rows=1,
        fetch_json=fake_fetch,
    )

    assert dois == ["10.3/baz", "10.4/qux"]
    assert fetch_call_count == 2


def test_fetch_all_dois_for_issn_merges_both_sources() -> None:
    """Merged DOI collection should de-duplicate across providers."""

    def fake_fetch(url: str, headers: dict[str, str] | None) -> dict[str, object]:
        if "sources/issn:" in url:
            return {"id": "https://openalex.org/S123"}

        if "api.openalex.org/works" in url:
            return {
                "results": [
                    {"doi": "10.1/foo"},
                    {"doi": "10.2/bar"},
                ],
                "meta": {"next_cursor": ""},
            }

        if "api.crossref.org/works" in url:
            return {
                "message": {
                    "items": [
                        {"DOI": "10.2/bar"},
                        {"DOI": "10.3/baz"},
                    ],
                    "next-cursor": "",
                }
            }

        raise AssertionError(f"Unexpected URL: {url}")

    dois = doi_sources.fetch_all_dois_for_issn(
        issn="1467-9965",
        email="you@example.com",
        rows=1000,
        fetch_json=fake_fetch,
    )

    assert dois == ["10.1/foo", "10.2/bar", "10.3/baz"]


def test_write_doi_file_persists_sorted_values(tmp_path: Path) -> None:
    """The DOI queue file should be written in sorted order."""
    output_path = doi_sources.write_doi_file(
        dois_dir=tmp_path,
        issn="1467-9965",
        dois=["10.2/bar", "10.1/foo"],
    )

    assert output_path.read_text(encoding="utf-8") == "10.1/foo\n10.2/bar\n"
