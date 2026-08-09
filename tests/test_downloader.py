"""Tests for direct PDF download behavior."""

from __future__ import annotations

from http.client import IncompleteRead
from pathlib import Path

from paper_downloader import doi_sources, downloader
from paper_downloader.progress import (
    build_batch_progress_files,
    load_dois_from_file,
    load_logged_doi_list,
)


def build_config(tmp_path: Path) -> downloader.DownloadConfig:
    """Create a test download config rooted in one temporary directory."""
    return downloader.DownloadConfig(
        base_urls=("https://publisher.example/pdf",),
        pdf_root_dir=tmp_path / "pdfs",
        timeout_seconds=30,
    )


def test_build_doi_download_url_preserves_slashes() -> None:
    """The default URL shape should keep DOI slashes."""
    url = downloader.build_doi_download_url(
        base_url="https://publisher.example/pdf",
        doi="10.1111/mafi.12108",
    )

    assert url == "https://publisher.example/pdf/10.1111/mafi.12108"


def test_build_doi_download_urls_supports_multiple_base_urls() -> None:
    """The downloader should build one candidate URL per configured base URL."""
    urls = downloader.build_doi_download_urls(
        base_urls=(
            "https://first.example/pdf",
            "https://second.example/pdf",
        ),
        doi="10.1111/mafi.12108",
    )

    assert urls == [
        "https://first.example/pdf/10.1111/mafi.12108",
        "https://second.example/pdf/10.1111/mafi.12108",
    ]


def test_infer_filename_from_url_drops_encoded_path_segments() -> None:
    """Encoded slashes should not become separators in inferred filenames."""
    filename = downloader.infer_filename_from_url(
        "https://publisher.example/download/ignored%2Fpaper.pdf"
    )

    assert filename == "paper.pdf"


def test_choose_base_filename_prefers_metadata_title() -> None:
    """A metadata title should win over the filename the server suggested."""
    response = downloader.BinaryHttpResponse(
        url="https://publisher.example/download/main.pdf",
        status_code=200,
        headers={},
        body=b"%PDF-1.7",
    )

    assert (
        downloader.choose_base_filename(response, "A Better Paper Name")
        == "A Better Paper Name.pdf"
    )


def test_choose_base_filename_falls_back_to_server_filename() -> None:
    """Without a metadata title, the server-suggested filename is kept."""
    response = downloader.BinaryHttpResponse(
        url="https://publisher.example/download/main.pdf",
        status_code=200,
        headers={},
        body=b"%PDF-1.7",
    )

    assert downloader.choose_base_filename(response, None) == "main.pdf"


def test_download_one_doi_saves_valid_pdf(monkeypatch, tmp_path: Path) -> None:
    """A valid PDF response should be written into the year-specific folder."""
    config = build_config(tmp_path)
    pdf_bytes = b"%PDF-1.7\n" + (b"0" * 256)

    monkeypatch.setattr(
        downloader.naming,
        "lookup_doi_metadata",
        lambda doi: ("A Useful Title", "2024"),
    )

    def fake_fetch(
        url: str,
        timeout_seconds: int,
        user_agent: str,
        referer: str | None,
    ) -> downloader.BinaryHttpResponse:
        return downloader.BinaryHttpResponse(
            url=url,
            status_code=200,
            headers={"content-type": "application/pdf"},
            body=pdf_bytes,
        )

    saved_pdf_path = downloader.download_one_doi(
        doi="10.1111/mafi.12108",
        issn="1467-9965",
        config=config,
        fetcher=fake_fetch,
    )

    assert saved_pdf_path.exists()
    assert saved_pdf_path.parent == tmp_path / "pdfs" / "1467-9965" / "2024"
    assert saved_pdf_path.name == "A Useful Title__doi_10.1111__mafi.12108.pdf"


def test_download_one_doi_saves_valid_pdf_when_metadata_lookup_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """A metadata outage should not discard already-fetched PDF bytes."""
    config = build_config(tmp_path)
    pdf_bytes = b"%PDF-1.7\n" + (b"0" * 256)

    def failing_metadata_lookup(doi: str) -> tuple[str | None, str | None]:
        """Simulate Crossref or OpenAlex being unavailable during save."""
        raise RuntimeError("metadata outage")

    monkeypatch.setattr(
        downloader.naming,
        "lookup_doi_metadata",
        failing_metadata_lookup,
    )

    def fake_fetch(
        url: str,
        timeout_seconds: int,
        user_agent: str,
        referer: str | None,
    ) -> downloader.BinaryHttpResponse:
        return downloader.BinaryHttpResponse(
            url=url,
            status_code=200,
            headers={"content-type": "application/pdf"},
            body=pdf_bytes,
        )

    saved_pdf_path = downloader.download_one_doi(
        doi="10.1111/mafi.12108",
        issn="1467-9965",
        config=config,
        fetcher=fake_fetch,
    )

    assert saved_pdf_path.exists()
    assert saved_pdf_path.parent == tmp_path / "pdfs" / "1467-9965"
    assert saved_pdf_path.name == "article__doi_10.1111__mafi.12108.pdf"


def test_download_one_doi_rejects_non_pdf_payload(tmp_path: Path) -> None:
    """An HTML payload should fail validation."""
    config = build_config(tmp_path)

    def fake_fetch(
        url: str,
        timeout_seconds: int,
        user_agent: str,
        referer: str | None,
    ) -> downloader.BinaryHttpResponse:
        return downloader.BinaryHttpResponse(
            url=url,
            status_code=200,
            headers={"content-type": "text/html"},
            body=b"<html>not a pdf</html>",
        )

    try:
        downloader.download_one_doi(
            doi="10.1111/mafi.12108",
            issn="1467-9965",
            config=config,
            fetcher=fake_fetch,
        )
    except downloader.DownloadError as exc:
        assert "not a valid PDF" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected DownloadError")


def test_run_download_batch_integration_with_mocked_http(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """A small end-to-end batch should collect DOIs and save PDFs."""

    def fake_metadata_fetch(
        url: str, headers: dict[str, str] | None
    ) -> dict[str, object]:
        if "sources/issn:" in url:
            return {"id": "https://openalex.org/S123"}

        if "api.openalex.org/works" in url:
            return {
                "results": [{"doi": "10.1/foo"}],
                "meta": {"next_cursor": ""},
            }

        if "api.crossref.org/works?" in url:
            if "select=DOI" in url:
                return {
                    "message": {
                        "items": [{"DOI": "10.2/bar"}],
                        "next-cursor": "",
                    }
                }

            raise AssertionError(f"Unexpected Crossref works URL: {url}")

        raise AssertionError(f"Unexpected URL: {url}")

    doi_list = doi_sources.fetch_all_dois_for_issn(
        issn="1467-9965",
        email="you@example.com",
        rows=1000,
        fetch_json=fake_metadata_fetch,
    )
    dois_file = doi_sources.write_doi_file(tmp_path / "dois", "1467-9965", doi_list)
    progress_files = build_batch_progress_files(dois_file)
    loaded_dois = load_dois_from_file(dois_file)
    config = build_config(tmp_path)
    pdf_bytes = b"%PDF-1.7\n" + (b"1" * 256)

    monkeypatch.setattr(
        downloader.naming,
        "lookup_doi_metadata",
        lambda doi: (f"Title for {doi}", "2023"),
    )

    def fake_pdf_fetch(
        url: str,
        timeout_seconds: int,
        user_agent: str,
        referer: str | None,
    ) -> downloader.BinaryHttpResponse:
        return downloader.BinaryHttpResponse(
            url=url,
            status_code=200,
            headers={"content-type": "application/pdf"},
            body=pdf_bytes,
        )

    exit_code = downloader.run_download_batch(
        dois=loaded_dois,
        issn="1467-9965",
        config=config,
        progress_files=progress_files,
        fetcher=fake_pdf_fetch,
    )

    assert exit_code == 0
    saved_pdfs = sorted((tmp_path / "pdfs" / "1467-9965" / "2023").glob("*.pdf"))
    assert [pdf.name for pdf in saved_pdfs] == [
        "Title for 10.1 foo__doi_10.1__foo.pdf",
        "Title for 10.2 bar__doi_10.2__bar.pdf",
    ]
    assert progress_files.success_path.exists()
    assert not load_dois_from_file(dois_file)


def test_run_download_batch_retries_current_error_ledger_once(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Current-pass failures should be retried once after the queue finishes."""
    dois_file = tmp_path / "dois" / "1467-9965_dois.txt"
    dois_file.parent.mkdir(parents=True, exist_ok=True)
    dois_file.write_text("10.1/foo\n", encoding="utf-8")

    progress_files = build_batch_progress_files(dois_file)
    loaded_dois = load_dois_from_file(dois_file)
    config = build_config(tmp_path)
    pdf_bytes = b"%PDF-1.7\n" + (b"6" * 256)
    attempt_count = 0

    monkeypatch.setattr(
        downloader.naming,
        "lookup_doi_metadata",
        lambda doi: ("Retried Successfully", "2024"),
    )

    def fake_fetch(
        url: str,
        timeout_seconds: int,
        user_agent: str,
        referer: str | None,
    ) -> downloader.BinaryHttpResponse:
        nonlocal attempt_count
        attempt_count += 1

        if attempt_count == 1:
            return downloader.BinaryHttpResponse(
                url=url,
                status_code=200,
                headers={"content-type": "text/html"},
                body=b"<html>temporary upstream failure</html>",
            )

        return downloader.BinaryHttpResponse(
            url=url,
            status_code=200,
            headers={"content-type": "application/pdf"},
            body=pdf_bytes,
        )

    exit_code = downloader.run_download_batch(
        dois=loaded_dois,
        issn="1467-9965",
        config=config,
        progress_files=progress_files,
        fetcher=fake_fetch,
    )

    assert exit_code == 0
    assert attempt_count == 2
    assert load_dois_from_file(dois_file) == []
    assert load_logged_doi_list(progress_files.error_path) == []
    assert load_logged_doi_list(progress_files.success_path) == ["10.1/foo"]


def test_run_download_batch_uses_configured_inter_download_pause(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Each non-terminal DOI transition should sleep for the configured gap."""
    dois_file = tmp_path / "dois" / "1467-9965_dois.txt"
    dois_file.parent.mkdir(parents=True, exist_ok=True)
    dois_file.write_text("10.1/foo\n10.2/bar\n", encoding="utf-8")

    progress_files = build_batch_progress_files(dois_file)
    loaded_dois = load_dois_from_file(dois_file)
    config = downloader.DownloadConfig(
        base_urls=("https://publisher.example/pdf",),
        pdf_root_dir=tmp_path / "pdfs",
        timeout_seconds=30,
        inter_download_sleep_seconds=0.25,
    )
    pdf_bytes = b"%PDF-1.7\n" + (b"1" * 256)
    slept_seconds: list[float] = []

    monkeypatch.setattr(
        downloader.naming,
        "lookup_doi_metadata",
        lambda doi: (f"Title for {doi}", "2024"),
    )

    def fake_fetch(
        url: str,
        timeout_seconds: int,
        user_agent: str,
        referer: str | None,
    ) -> downloader.BinaryHttpResponse:
        return downloader.BinaryHttpResponse(
            url=url,
            status_code=200,
            headers={"content-type": "application/pdf"},
            body=pdf_bytes,
        )

    exit_code = downloader.run_download_batch(
        dois=loaded_dois,
        issn="1467-9965",
        config=config,
        progress_files=progress_files,
        fetcher=fake_fetch,
        sleep_fn=slept_seconds.append,
    )

    assert exit_code == 0
    assert slept_seconds == [0.25]


def test_run_download_batch_retry_error_dois_cleans_error_ledger_on_success(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Manual error-ledger retries should remove DOI rows after success."""
    dois_file = tmp_path / "dois" / "1467-9965_dois.txt"
    dois_file.parent.mkdir(parents=True, exist_ok=True)
    dois_file.write_text("", encoding="utf-8")

    progress_files = build_batch_progress_files(dois_file)
    progress_files.error_path.write_text(
        "doi=10.2/bar | status=download_error | ts=2026-04-08T12:00:00\n",
        encoding="utf-8",
    )
    config = build_config(tmp_path)
    pdf_bytes = b"%PDF-1.7\n" + (b"7" * 256)

    monkeypatch.setattr(
        downloader.naming,
        "lookup_doi_metadata",
        lambda doi: ("Recovered From Error Ledger", "2024"),
    )

    def fake_fetch(
        url: str,
        timeout_seconds: int,
        user_agent: str,
        referer: str | None,
    ) -> downloader.BinaryHttpResponse:
        return downloader.BinaryHttpResponse(
            url=url,
            status_code=200,
            headers={"content-type": "application/pdf"},
            body=pdf_bytes,
        )

    exit_code = downloader.run_download_batch(
        dois=[],
        issn="1467-9965",
        config=config,
        progress_files=progress_files,
        retry_error_dois=True,
        fetcher=fake_fetch,
    )

    assert exit_code == 0
    assert load_logged_doi_list(progress_files.error_path) == []
    assert load_logged_doi_list(progress_files.success_path) == ["10.2/bar"]


def test_run_download_batch_reports_skipped_error_ledger_dois(
    capsys,
    tmp_path: Path,
) -> None:
    """A fully parked queue should explain why no DOI values are attempted."""
    dois_file = tmp_path / "dois" / "1467-9965_dois.txt"
    dois_file.parent.mkdir(parents=True, exist_ok=True)
    dois_file.write_text("10.1/foo\n10.2/bar\n", encoding="utf-8")

    progress_files = build_batch_progress_files(dois_file)
    progress_files.error_path.write_text(
        "\n".join(
            [
                "doi=10.1/foo | status=download_error | ts=2026-05-11T12:00:00",
                "doi=10.2/bar | status=download_error | ts=2026-05-11T12:00:01",
            ]
        ),
        encoding="utf-8",
    )
    config = build_config(tmp_path)

    exit_code = downloader.run_download_batch(
        dois=load_dois_from_file(dois_file),
        issn="1467-9965",
        config=config,
        progress_files=progress_files,
        retry_error_dois=False,
    )

    captured_output = capsys.readouterr().out

    assert exit_code == 0
    assert "Skipping 2 DOI(s) already recorded in" in captured_output
    assert "--retry-error-dois" in captured_output


def test_stale_success_retry_records_fresh_pdf_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """A stale success row should be replaced by a fresh success with `pdf=`."""
    dois_file = tmp_path / "dois" / "1467-9965_dois.txt"
    dois_file.parent.mkdir(parents=True, exist_ok=True)
    dois_file.write_text("", encoding="utf-8")

    progress_files = build_batch_progress_files(dois_file)
    progress_files.success_path.write_text(
        "doi=10.1/foo | status=success | ts=2026-04-08T12:00:00\n",
        encoding="utf-8",
    )
    config = build_config(tmp_path)
    pdf_bytes = b"%PDF-1.7\n" + (b"8" * 256)

    monkeypatch.setattr(
        downloader.naming,
        "lookup_doi_metadata",
        lambda doi: ("Freshly Downloaded", "2026"),
    )

    def fake_fetch(
        url: str,
        timeout_seconds: int,
        user_agent: str,
        referer: str | None,
    ) -> downloader.BinaryHttpResponse:
        return downloader.BinaryHttpResponse(
            url=url,
            status_code=200,
            headers={"content-type": "application/pdf"},
            body=pdf_bytes,
        )

    exit_code = downloader.run_download_batch(
        dois=[],
        issn="1467-9965",
        config=config,
        progress_files=progress_files,
        fetcher=fake_fetch,
    )

    success_lines = progress_files.success_path.read_text(encoding="utf-8").splitlines()

    assert exit_code == 0
    assert len(success_lines) == 1
    assert "doi=10.1/foo" in success_lines[0]
    assert "status=success" in success_lines[0]
    assert "pdf=Freshly Downloaded__doi_10.1__foo.pdf" in success_lines[0]


def test_download_one_doi_follows_html_iframe_to_pdf(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """An HTML viewer page should be resolved to its embedded PDF URL."""
    config = build_config(tmp_path)
    pdf_bytes = b"%PDF-1.7\n" + (b"2" * 256)
    html_bytes = b'<html><body><iframe src="/viewer/article.pdf?download=true"></iframe></body></html>'

    monkeypatch.setattr(
        downloader.naming,
        "lookup_doi_metadata",
        lambda doi: ("Resolved Through Viewer", "2022"),
    )

    def fake_fetch(
        url: str,
        timeout_seconds: int,
        user_agent: str,
        referer: str | None,
    ) -> downloader.BinaryHttpResponse:
        if url.endswith("/10.1111/mafi.12108"):
            return downloader.BinaryHttpResponse(
                url=url,
                status_code=200,
                headers={"content-type": "text/html; charset=UTF-8"},
                body=html_bytes,
            )

        if "article.pdf" in url:
            assert referer == "https://publisher.example/pdf/10.1111/mafi.12108"
            return downloader.BinaryHttpResponse(
                url=url,
                status_code=200,
                headers={"content-type": "application/pdf"},
                body=pdf_bytes,
            )

        raise AssertionError(f"Unexpected URL: {url}")

    saved_pdf_path = downloader.download_one_doi(
        doi="10.1111/mafi.12108",
        issn="1467-9965",
        config=config,
        fetcher=fake_fetch,
    )

    assert saved_pdf_path.exists()
    assert saved_pdf_path.name == "Resolved Through Viewer__doi_10.1111__mafi.12108.pdf"


def test_download_one_doi_falls_back_to_second_base_url(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """If the first base URL fails, the next configured base URL should run."""
    config = downloader.DownloadConfig(
        base_urls=(
            "https://bad.example/pdf",
            "https://good.example/pdf",
        ),
        pdf_root_dir=tmp_path / "pdfs",
        timeout_seconds=30,
    )
    pdf_bytes = b"%PDF-1.7\n" + (b"4" * 256)

    monkeypatch.setattr(
        downloader.naming,
        "lookup_doi_metadata",
        lambda doi: ("Second Base URL Worked", "2025"),
    )
    monkeypatch.setattr(downloader.random, "randrange", lambda _: 0)

    def fake_fetch(
        url: str,
        timeout_seconds: int,
        user_agent: str,
        referer: str | None,
    ) -> downloader.BinaryHttpResponse:
        if url.startswith("https://bad.example/"):
            return downloader.BinaryHttpResponse(
                url=url,
                status_code=200,
                headers={"content-type": "text/html"},
                body=b"<html>no pdf here</html>",
            )

        if url.startswith("https://good.example/"):
            return downloader.BinaryHttpResponse(
                url=url,
                status_code=200,
                headers={"content-type": "application/pdf"},
                body=pdf_bytes,
            )

        raise AssertionError(f"Unexpected URL: {url}")

    saved_pdf_path = downloader.download_one_doi(
        doi="10.1111/mafi.12108",
        issn="1467-9965",
        config=config,
        fetcher=fake_fetch,
    )

    assert saved_pdf_path.exists()
    assert saved_pdf_path.name == "Second Base URL Worked__doi_10.1111__mafi.12108.pdf"


def test_download_one_doi_randomizes_which_base_url_goes_first(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Each DOI should start from one random base URL before exhausting the list."""
    config = downloader.DownloadConfig(
        base_urls=(
            "https://first.example/pdf",
            "https://second.example/pdf",
            "https://third.example/pdf",
        ),
        pdf_root_dir=tmp_path / "pdfs",
        timeout_seconds=30,
    )
    pdf_bytes = b"%PDF-1.7\n" + (b"9" * 256)
    attempted_urls: list[str] = []

    monkeypatch.setattr(
        downloader.naming,
        "lookup_doi_metadata",
        lambda doi: ("Randomized URL Order", "2025"),
    )
    monkeypatch.setattr(downloader.random, "randrange", lambda _: 1)

    def fake_fetch(
        url: str,
        timeout_seconds: int,
        user_agent: str,
        referer: str | None,
    ) -> downloader.BinaryHttpResponse:
        attempted_urls.append(url)

        if url.startswith("https://second.example/"):
            return downloader.BinaryHttpResponse(
                url=url,
                status_code=200,
                headers={"content-type": "text/html"},
                body=b"<html>not the right endpoint</html>",
            )

        return downloader.BinaryHttpResponse(
            url=url,
            status_code=200,
            headers={"content-type": "application/pdf"},
            body=pdf_bytes,
        )

    saved_pdf_path = downloader.download_one_doi(
        doi="10.1111/mafi.12108",
        issn="1467-9965",
        config=config,
        fetcher=fake_fetch,
    )

    assert saved_pdf_path.exists()
    assert attempted_urls == [
        "https://second.example/pdf/10.1111/mafi.12108",
        "https://third.example/pdf/10.1111/mafi.12108",
    ]


def test_download_one_doi_follows_citation_pdf_url_meta(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """A citation_pdf_url meta tag should be treated as the PDF target."""
    config = build_config(tmp_path)
    pdf_bytes = b"%PDF-1.7\n" + (b"3" * 256)
    html_bytes = (
        b'<html><head><meta name="citation_pdf_url" '
        b'content="https://publisher.example/downloads/final.pdf"></head></html>'
    )

    monkeypatch.setattr(
        downloader.naming,
        "lookup_doi_metadata",
        lambda doi: ("Meta Resolved Paper", "2021"),
    )

    def fake_fetch(
        url: str,
        timeout_seconds: int,
        user_agent: str,
        referer: str | None,
    ) -> downloader.BinaryHttpResponse:
        if url.endswith("/10.1111/mafi.12108"):
            return downloader.BinaryHttpResponse(
                url=url,
                status_code=200,
                headers={"content-type": "text/html"},
                body=html_bytes,
            )

        if url == "https://publisher.example/downloads/final.pdf":
            return downloader.BinaryHttpResponse(
                url=url,
                status_code=200,
                headers={"content-type": "application/pdf"},
                body=pdf_bytes,
            )

        raise AssertionError(f"Unexpected URL: {url}")

    saved_pdf_path = downloader.download_one_doi(
        doi="10.1111/mafi.12108",
        issn="1467-9965",
        config=config,
        fetcher=fake_fetch,
    )

    assert saved_pdf_path.exists()
    assert saved_pdf_path.name == "Meta Resolved Paper__doi_10.1111__mafi.12108.pdf"


def test_download_one_doi_uses_nested_html_page_as_followup_referer(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Nested resolver hops should send the immediate parent page as referer."""
    config = build_config(tmp_path)
    pdf_bytes = b"%PDF-1.7\n" + (b"4" * 256)
    root_html = b'<html><body><a href="/doi/pdf/step2"></a></body></html>'
    nested_html = b'<html><body><a href="/final.pdf"></a></body></html>'
    final_pdf_referer: str | None = None

    monkeypatch.setattr(
        downloader.naming,
        "lookup_doi_metadata",
        lambda doi: ("Nested Referer Resolution", "2025"),
    )

    def fake_fetch(
        url: str,
        timeout_seconds: int,
        user_agent: str,
        referer: str | None,
    ) -> downloader.BinaryHttpResponse:
        nonlocal final_pdf_referer

        if url.endswith("/10.1111/mafi.12108"):
            return downloader.BinaryHttpResponse(
                url=url,
                status_code=200,
                headers={"content-type": "text/html"},
                body=root_html,
            )

        if url.endswith("/doi/pdf/step2"):
            assert referer == "https://publisher.example/pdf/10.1111/mafi.12108"
            return downloader.BinaryHttpResponse(
                url=url,
                status_code=200,
                headers={"content-type": "text/html"},
                body=nested_html,
            )

        if url.endswith("/final.pdf"):
            final_pdf_referer = referer
            return downloader.BinaryHttpResponse(
                url=url,
                status_code=200,
                headers={"content-type": "application/pdf"},
                body=pdf_bytes,
            )

        raise AssertionError(f"Unexpected URL: {url}")

    saved_pdf_path = downloader.download_one_doi(
        doi="10.1111/mafi.12108",
        issn="1467-9965",
        config=config,
        fetcher=fake_fetch,
    )

    assert saved_pdf_path.exists()
    assert final_pdf_referer == "https://publisher.example/doi/pdf/step2"


def test_http_pdf_resolution_stops_at_depth_limit() -> None:
    """Direct HTTP HTML resolution should stop at the configured depth."""
    html_headers = {"content-type": "text/html"}
    max_depth_html_response = downloader.BinaryHttpResponse(
        url="https://publisher.example/second.pdf?download=true",
        status_code=200,
        headers=html_headers,
        body=b'<html><body><a href="/third.pdf"></a></body></html>',
    )

    def fake_fetch(
        url: str,
        timeout_seconds: int,
        user_agent: str,
        referer: str | None,
    ) -> downloader.BinaryHttpResponse:
        raise AssertionError(f"Depth limit should prevent fetching {url}")

    http_resolved_response = downloader.resolve_pdf_response(
        response=max_depth_html_response,
        timeout_seconds=30,
        user_agent="paper-downloader-test",
        fetcher=fake_fetch,
        depth=downloader.PDF_RESOLUTION_MAX_DEPTH,
    )

    assert http_resolved_response is max_depth_html_response


def test_fetch_binary_response_retries_incomplete_read(monkeypatch) -> None:
    """Transient incomplete reads should be retried before failing."""
    complete_pdf_bytes = b"%PDF-1.7\n" + (b"8" * 256)
    urlopen_call_count = 0

    class FakeResponse:
        """Small context-manager response used to test retry behavior."""

        def __init__(self, *, raise_incomplete_read: bool) -> None:
            self.raise_incomplete_read = raise_incomplete_read
            self.headers = {"Content-Type": "application/pdf"}
            self.status = 200

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def read(self) -> bytes:
            if self.raise_incomplete_read:
                raise IncompleteRead(b"%PDF-1.7\npartial", len(complete_pdf_bytes))

            return complete_pdf_bytes

        def geturl(self) -> str:
            return "https://publisher.example/pdf/10.1111/mafi.12108"

    def fake_urlopen(request: object, timeout: int) -> FakeResponse:
        nonlocal urlopen_call_count
        urlopen_call_count += 1

        should_raise = urlopen_call_count < 3
        return FakeResponse(raise_incomplete_read=should_raise)

    monkeypatch.setattr(downloader, "urlopen", fake_urlopen)

    response = downloader.fetch_binary_response(
        url="https://publisher.example/pdf/10.1111/mafi.12108",
        timeout_seconds=30,
        user_agent="paper-downloader-test",
    )

    assert urlopen_call_count == 3
    assert response.status_code == 200
    assert response.body == complete_pdf_bytes
