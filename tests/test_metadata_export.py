"""Tests for DOI metadata export."""

from __future__ import annotations

import csv
import io
import threading
from pathlib import Path

from paper_downloader.metadata import export as metadata_export


def test_reconstruct_openalex_abstract_orders_tokens() -> None:
    """OpenAlex abstract reconstruction should sort tokens by position."""
    abstract = metadata_export.reconstruct_openalex_abstract(
        {
            "world": [1],
            "Hello": [0],
            "again": [2],
        }
    )

    assert abstract == "Hello world again"


def test_reconstruct_openalex_abstract_preserves_position_collisions() -> None:
    """OpenAlex tokens sharing one position should all appear in the abstract."""
    abstract = metadata_export.reconstruct_openalex_abstract(
        {
            "Hello": [0],
            "world": [0, 2],
            "again": [1],
        }
    )

    assert abstract == "Hello world again world"


def test_build_metadata_record_merges_crossref_and_openalex_fields() -> None:
    """Crossref should supply bibliographic fields while OpenAlex enriches gaps."""

    def fake_fetch(
        url: str,
        headers: dict[str, str] | None,
        timeout_seconds: int,
    ) -> dict[str, object]:
        if "api.crossref.org" in url:
            return {
                "message": {
                    "title": ["Crossref Title"],
                    "author": [
                        {
                            "given": "Alice",
                            "family": "Smith",
                            "ORCID": "https://orcid.org/0000-0001-2345-6789",
                            "affiliation": [{"name": "Alpha University"}],
                        },
                        {"given": "Bob", "family": "Jones"},
                    ],
                    "published": {"date-parts": [[2024, 3, 15]]},
                    "container-title": ["Journal of Testing"],
                    "publisher": "Testing Press",
                }
            }

        if "api.openalex.org" in url:
            return {
                "title": "OpenAlex Title",
                "abstract_inverted_index": {
                    "Test": [0],
                    "abstract": [1],
                },
                "keywords": [
                    {"display_name": "Derivatives"},
                    {"display_name": "Risk Management"},
                ],
                "topics": [
                    {"display_name": "Asset Pricing"},
                    {"display_name": "Derivative Securities"},
                ],
            }

        raise AssertionError(f"Unexpected URL: {url}")

    record = metadata_export.build_metadata_record(
        doi="10.1000/test",
        email="you@example.com",
        fetch_json=fake_fetch,
    )

    assert record.doi == "10.1000/test"
    assert record.title == "Crossref Title"
    assert record.abstract == "Test abstract"
    assert record.authors == "Alice Smith; Bob Jones"
    assert record.orcid_ids == "0000-0001-2345-6789"
    assert record.affiliations == "Alice Smith: Alpha University"
    assert record.published_date == "2024-03-15"
    assert record.journal_title == "Journal of Testing"
    assert record.publisher == "Testing Press"
    assert record.keywords == "Derivatives; Risk Management"
    assert record.topics == "Asset Pricing; Derivative Securities"


def test_export_metadata_from_dois_writes_csv(tmp_path: Path) -> None:
    """The exporter should write one CSV row per DOI."""

    def fake_fetch(
        url: str,
        headers: dict[str, str] | None,
        timeout_seconds: int,
    ) -> dict[str, object]:
        if "api.crossref.org" in url:
            return {
                "message": {
                    "title": ["Sample Title"],
                    "author": [
                        {
                            "given": "Jane",
                            "family": "Doe",
                            "ORCID": "0000-0002-9876-5432",
                            "affiliation": [{"name": "Beta Capital"}],
                        }
                    ],
                    "published": {"date-parts": [[2020, 7, 1]]},
                    "container-title": ["Sample Journal"],
                    "publisher": "Sample Publisher",
                }
            }

        if "api.openalex.org" in url:
            return {
                "keywords": [{"display_name": "Volatility"}],
                "topics": [{"display_name": "Options Pricing"}],
            }

        raise AssertionError(f"Unexpected URL: {url}")

    output_csv_path = tmp_path / "metadata.csv"
    written_path = metadata_export.export_metadata_from_dois(
        dois=["10.1000/sample"],
        output_csv_path=output_csv_path,
        email="you@example.com",
        fetch_json=fake_fetch,
    )

    assert written_path == output_csv_path

    with output_csv_path.open("r", encoding="utf-8", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))

    assert len(rows) == 1
    assert rows[0]["doi"] == "10.1000/sample"
    assert rows[0]["title"] == "Sample Title"
    assert rows[0]["authors"] == "Jane Doe"
    assert rows[0]["orcid_ids"] == "0000-0002-9876-5432"
    assert rows[0]["affiliations"] == "Jane Doe: Beta Capital"
    assert rows[0]["published_date"] == "2020-07-01"
    assert rows[0]["journal_title"] == "Sample Journal"
    assert rows[0]["publisher"] == "Sample Publisher"
    assert rows[0]["keywords"] == "Volatility"
    assert rows[0]["topics"] == "Options Pricing"


def test_export_metadata_from_dois_reports_progress(tmp_path: Path) -> None:
    """The exporter should print one visible progress line per DOI."""

    def fake_fetch(
        url: str,
        headers: dict[str, str] | None,
        timeout_seconds: int,
    ) -> dict[str, object]:
        if "api.crossref.org" in url:
            return {"message": {"title": ["Progress Title"]}}

        if "api.openalex.org" in url:
            return {}

        raise AssertionError(f"Unexpected URL: {url}")

    output_csv_path = tmp_path / "metadata.csv"
    progress_stream = io.StringIO()

    metadata_export.export_metadata_from_dois(
        dois=["10.1000/one", "10.1000/two"],
        output_csv_path=output_csv_path,
        email="you@example.com",
        fetch_json=fake_fetch,
        progress_stream=progress_stream,
    )

    progress_output = progress_stream.getvalue()

    assert "Starting metadata export for 2 DOI(s)" in progress_output
    assert "[1/2]" in progress_output
    assert "10.1000/one" in progress_output
    assert "[2/2]" in progress_output
    assert "10.1000/two" in progress_output


def test_build_metadata_record_falls_back_to_openalex_enrichment() -> None:
    """OpenAlex should fill new enrichment fields when Crossref is sparse."""

    def fake_fetch(
        url: str,
        headers: dict[str, str] | None,
        timeout_seconds: int,
    ) -> dict[str, object]:
        if "api.crossref.org" in url:
            return {"message": {"title": ["Sparse Crossref Title"]}}

        if "api.openalex.org" in url:
            return {
                "title": "OpenAlex Title",
                "authorships": [
                    {
                        "author": {
                            "display_name": "Jane Quant",
                            "orcid": "https://orcid.org/0000-0003-1111-2222",
                        },
                        "institutions": [
                            {"display_name": "Gamma University"},
                        ],
                    }
                ],
                "publication_date": "2022-05-10",
                "primary_location": {
                    "raw_source_name": "Fallback Journal",
                    "source": {
                        "display_name": "Fallback Journal",
                        "host_organization_name": "Fallback Publisher",
                    },
                },
                "topics": [
                    {"display_name": "Stochastic Processes"},
                ],
            }

        raise AssertionError(f"Unexpected URL: {url}")

    record = metadata_export.build_metadata_record(
        doi="10.1000/fallback",
        email="you@example.com",
        fetch_json=fake_fetch,
    )

    assert record.orcid_ids == "0000-0003-1111-2222"
    assert record.affiliations == "Jane Quant: Gamma University"
    assert record.journal_title == "Fallback Journal"
    assert record.publisher == "Fallback Publisher"
    assert record.topics == "Stochastic Processes"


def test_build_default_metadata_csv_path_uses_queue_stem() -> None:
    """The default CSV path should use the metadata directory and queue stem."""
    output_path = metadata_export.build_default_metadata_csv_path(
        dois_file_path=Path("/tmp/data/interim/doi_queues/1467-9965_dois.txt"),
        metadata_dir=Path("/tmp/outputs/metadata"),
    )

    assert output_path == Path("/tmp/outputs/metadata/1467-9965_metadata.csv")


def test_export_metadata_from_dois_continues_after_one_doi_fails(
    tmp_path: Path,
) -> None:
    """One DOI failure should not abort the rest of the batch."""
    fetch_call_count = 0

    def fake_fetch(
        url: str,
        headers: dict[str, str] | None,
        timeout_seconds: int,
    ) -> dict[str, object]:
        nonlocal fetch_call_count
        fetch_call_count += 1

        if "10.1000%2Fbad" in url:
            raise RuntimeError("simulated provider failure")

        if "api.crossref.org" in url:
            return {
                "message": {
                    "title": ["Healthy Record"],
                    "published": {"date-parts": [[2024, 1, 1]]},
                }
            }

        if "api.openalex.org" in url:
            return {}

        raise AssertionError(f"Unexpected URL: {url}")

    output_csv_path = tmp_path / "metadata.csv"
    progress_stream = io.StringIO()
    written_path = metadata_export.export_metadata_from_dois(
        dois=["10.1000/bad", "10.1000/good"],
        output_csv_path=output_csv_path,
        email="you@example.com",
        fetch_json=fake_fetch,
        progress_stream=progress_stream,
    )

    assert written_path == output_csv_path

    with output_csv_path.open("r", encoding="utf-8", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))

    assert len(rows) == 2
    assert rows[0]["doi"] == "10.1000/bad"
    assert rows[0]["title"] == ""
    assert rows[0]["published_date"] == ""
    assert rows[1]["doi"] == "10.1000/good"
    assert rows[1]["title"] == "Healthy Record"

    progress_output = progress_stream.getvalue()
    assert "failed metadata for DOI 10.1000/bad" in progress_output
    assert "[2/2]" in progress_output


def test_export_metadata_from_dois_runs_parallel_workers_and_preserves_order(
    tmp_path: Path,
) -> None:
    """Parallel export should keep CSV rows in the original DOI order."""
    fast_fetch_started = threading.Event()

    def fake_fetch(
        url: str,
        headers: dict[str, str] | None,
        timeout_seconds: int,
    ) -> dict[str, object]:
        if "api.openalex.org" in url:
            return {}

        if "10.1000%2Fslow" in url:
            fast_fetch_started.wait(timeout=1.0)
            return {"message": {"title": ["Slow Title"]}}

        if "10.1000%2Ffast" in url:
            fast_fetch_started.set()
            return {"message": {"title": ["Fast Title"]}}

        raise AssertionError(f"Unexpected URL: {url}")

    output_csv_path = tmp_path / "metadata.csv"
    metadata_export.export_metadata_from_dois(
        dois=["10.1000/slow", "10.1000/fast"],
        output_csv_path=output_csv_path,
        email="you@example.com",
        fetch_json=fake_fetch,
        progress_stream=io.StringIO(),
        max_workers=2,
    )

    with output_csv_path.open("r", encoding="utf-8", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))

    assert fast_fetch_started.is_set()
    assert [row["doi"] for row in rows] == ["10.1000/slow", "10.1000/fast"]
    assert [row["title"] for row in rows] == ["Slow Title", "Fast Title"]


def test_build_paced_json_fetcher_spaces_requests_to_same_host() -> None:
    """Paced fetching should avoid tight repeated requests to one provider."""
    sleeps: list[float] = []
    current_time = 100.0

    def fake_sleep(seconds: float) -> None:
        nonlocal current_time
        sleeps.append(seconds)
        current_time += seconds

    def fake_monotonic() -> float:
        return current_time

    def fake_fetch(
        url: str,
        headers: dict[str, str] | None,
        timeout_seconds: int,
    ) -> dict[str, object]:
        return {"url": url}

    paced_fetch = metadata_export.build_paced_json_fetcher(
        fetch_json=fake_fetch,
        request_delay_seconds=0.25,
        sleep=fake_sleep,
        monotonic=fake_monotonic,
    )

    paced_fetch("https://api.crossref.org/works/one", None, 60)
    paced_fetch("https://api.crossref.org/works/two", None, 60)
    paced_fetch("https://api.openalex.org/works/three", None, 60)

    assert sleeps == [0.25]


def test_build_metadata_record_uses_openalex_when_crossref_fails() -> None:
    """A Crossref outage should not prevent OpenAlex metadata enrichment."""

    def fake_fetch(
        url: str,
        headers: dict[str, str] | None,
        timeout_seconds: int,
    ) -> dict[str, object]:
        if "api.crossref.org" in url:
            raise RuntimeError("crossref outage")

        if "api.openalex.org" in url:
            return {
                "title": "OpenAlex Survived Crossref Failure",
                "publication_date": "2024-02-03",
                "topics": [{"display_name": "Market Microstructure"}],
            }

        raise AssertionError(f"Unexpected URL: {url}")

    record = metadata_export.build_metadata_record(
        doi="10.1000/openalex-only",
        email="you@example.com",
        fetch_json=fake_fetch,
    )

    assert record.title == "OpenAlex Survived Crossref Failure"
    assert record.published_date == "2024-02-03"
    assert record.topics == "Market Microstructure"
