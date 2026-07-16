"""Tests for CLI configuration loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from paper_downloader import cli, config


def test_parse_base_urls_supports_comma_separated_values() -> None:
    """Comma-separated base URLs from `.env` should preserve order."""
    parsed_urls = cli.parse_base_urls("https://first.example, https://second.example")

    assert parsed_urls == (
        "https://first.example",
        "https://second.example",
    )


def test_parse_base_urls_normalizes_messy_base_url_formats() -> None:
    """Base URLs should tolerate missing schemes and trailing slashes."""
    parsed_urls = cli.parse_base_urls(
        "publisher.example/pdf/, www.second.example/doi/pdf//, https://third.example/path/"
    )

    assert parsed_urls == (
        "https://publisher.example/pdf",
        "https://www.second.example/doi/pdf",
        "https://third.example/path",
    )


def test_parse_base_urls_deduplicates_after_normalization() -> None:
    """Equivalent URLs should collapse after normalization."""
    parsed_urls = cli.parse_base_urls(
        [
            "publisher.example/pdf/",
            "https://publisher.example/pdf",
            "HTTPS://Publisher.Example/pdf//",
        ]
    )

    assert parsed_urls == ("https://publisher.example/pdf",)


def test_load_env_file_reads_dotenv_values(tmp_path: Path) -> None:
    """The local `.env` loader should parse simple key-value pairs."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        "PAPER_DOWNLOADER_BASE_URLS=https://first.example,https://second.example\n",
        encoding="utf-8",
    )

    env_values = config.load_env_file(env_path)

    assert (
        env_values["PAPER_DOWNLOADER_BASE_URLS"]
        == "https://first.example,https://second.example"
    )


def test_load_env_file_handles_export_prefix(tmp_path: Path) -> None:
    """The local `.env` loader should accept shell-style `export` lines."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "export PAPER_DOWNLOADER_BASE_URLS=https://first.example/pdf",
                "PAPER_DOWNLOADER_EMAIL=user@example.com",
            ]
        ),
        encoding="utf-8",
    )

    env_values = config.load_env_file(env_path)

    assert "export PAPER_DOWNLOADER_BASE_URLS" not in env_values
    assert env_values["PAPER_DOWNLOADER_BASE_URLS"] == "https://first.example/pdf"
    assert env_values["PAPER_DOWNLOADER_EMAIL"] == "user@example.com"


def test_parse_export_metadata_args_accepts_explicit_doi_file() -> None:
    """The metadata export entrypoint should still accept one DOI queue file."""
    parsed_args = cli.parse_export_metadata_args(
        ["--dois-file", "data/interim/doi_queues/example.txt"]
    )

    assert parsed_args.dois_file == Path("data/interim/doi_queues/example.txt")


def test_parse_export_metadata_args_accepts_max_workers() -> None:
    """The metadata export entrypoint should accept a parallel worker count."""
    parsed_args = cli.parse_export_metadata_args(["--max-workers", "12"])

    assert parsed_args.max_workers == 12


def test_parse_export_metadata_args_accepts_request_delay_seconds() -> None:
    """The metadata export entrypoint should accept API request pacing."""
    parsed_args = cli.parse_export_metadata_args(["--request-delay-seconds", "0.2"])

    assert parsed_args.request_delay_seconds == 0.2


def test_parse_download_args_allows_config_only_execution() -> None:
    """The download entrypoint should allow config-driven DOI queue selection."""
    parsed_args = cli.parse_download_args([])

    assert parsed_args.doi is None
    assert parsed_args.dois_file is None


def test_parse_download_args_rejects_removed_browser_flags() -> None:
    """The download entrypoint should no longer accept browser-mode flags."""
    with pytest.raises(SystemExit):
        cli.parse_download_args(["--use-browser"])


def test_load_config_rejects_removed_browser_settings(tmp_path: Path) -> None:
    """Config loading should reject stale browser-mode settings."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                'base_url = "https://publisher.example/pdf"',
                'email = "user@example.com"',
                "crossref_rows = 1000",
                "timeout_seconds = 60",
                "use_browser = true",
                'dois_dir = "data/interim/doi_queues"',
                'metadata_dir = "outputs/metadata"',
                'pdfs_dir = "outputs/pdfs"',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="use_browser"):
        cli.load_config(config_path)


def test_load_config_rejects_non_positive_numeric_settings(tmp_path: Path) -> None:
    """Numeric config values that bound external requests must be positive."""
    invalid_settings = [
        ("crossref_rows", 0),
        ("crossref_rows", -1),
        ("timeout_seconds", 0),
        ("timeout_seconds", -1),
    ]

    for setting_name, setting_value in invalid_settings:
        config_path = tmp_path / f"{setting_name}_{setting_value}.toml"
        crossref_rows = setting_value if setting_name == "crossref_rows" else 1000
        timeout_seconds = setting_value if setting_name == "timeout_seconds" else 60
        config_path.write_text(
            "\n".join(
                [
                    'base_url = "https://publisher.example/pdf"',
                    'doi_file = "data/interim/doi_queues/1467-9965_dois.txt"',
                    'email = "user@example.com"',
                    f"crossref_rows = {crossref_rows}",
                    f"timeout_seconds = {timeout_seconds}",
                    'dois_dir = "data/interim/doi_queues"',
                    'metadata_dir = "outputs/metadata"',
                    'pdfs_dir = "outputs/pdfs"',
                ]
            ),
            encoding="utf-8",
        )

        try:
            cli.load_config(config_path)
        except ValueError as exc:
            assert setting_name in str(exc)
            assert "positive" in str(exc)
        else:  # pragma: no cover
            raise AssertionError(f"Expected ValueError for {setting_name}")


def test_load_config_rejects_non_string_doi_files(tmp_path: Path) -> None:
    """Configured DOI queue paths must be strings, not arbitrary TOML values."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                'base_url = "https://publisher.example/pdf"',
                'doi_files = ["data/interim/doi_queues/1467-9965_dois.txt", 123]',
                'email = "user@example.com"',
                "crossref_rows = 1000",
                "timeout_seconds = 60",
                'dois_dir = "data/interim/doi_queues"',
                'metadata_dir = "outputs/metadata"',
                'pdfs_dir = "outputs/pdfs"',
            ]
        ),
        encoding="utf-8",
    )

    try:
        cli.load_config(config_path)
    except ValueError as exc:
        assert "doi_files" in str(exc)
        assert "strings" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected ValueError")


def test_load_config_rejects_directory_setting_that_points_to_file(
    tmp_path: Path,
) -> None:
    """Configured output directories must not resolve to existing files."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                'base_url = "https://publisher.example/pdf"',
                'doi_file = ""',
                'email = "user@example.com"',
                "crossref_rows = 1000",
                "timeout_seconds = 60",
                'dois_dir = "config.toml"',
                'metadata_dir = "outputs/metadata"',
                'pdfs_dir = "outputs/pdfs"',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="dois_dir"):
        cli.load_config(config_path)


def test_run_fetch_dois_rejects_empty_email(monkeypatch, tmp_path: Path) -> None:
    """Crossref DOI collection requires a non-empty polite-pool email."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                'base_url = "https://publisher.example/pdf"',
                'doi_file = "data/interim/doi_queues/1467-9965_dois.txt"',
                'email = ""',
                "crossref_rows = 1000",
                "timeout_seconds = 60",
                'dois_dir = "data/interim/doi_queues"',
                'metadata_dir = "outputs/metadata"',
                'pdfs_dir = "outputs/pdfs"',
            ]
        ),
        encoding="utf-8",
    )
    parsed_args = cli.parse_fetch_dois_args(["--issn", "1467-9965"])
    parsed_args.config = config_path

    def unexpected_fetch(*args: object, **kwargs: object) -> list[str]:
        raise AssertionError("Crossref should not be called without email")

    monkeypatch.setattr(cli, "fetch_all_dois_for_issn", unexpected_fetch)

    try:
        cli.run_fetch_dois(parsed_args)
    except SystemExit as exc:
        assert "email" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected SystemExit")


def test_run_download_uses_configured_doi_file_list_in_order(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Config-provided DOI queue files should run sequentially."""
    first_dois_file = (
        tmp_path / "data" / "interim" / "doi_queues" / "1467-9965_dois.txt"
    )
    second_dois_file = (
        tmp_path / "data" / "interim" / "doi_queues" / "2214-6369_dois.txt"
    )
    first_dois_file.parent.mkdir(parents=True, exist_ok=True)
    first_dois_file.write_text("10.1111/first\n", encoding="utf-8")
    second_dois_file.write_text("10.2222/second\n", encoding="utf-8")

    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                'base_url = "https://publisher.example/pdf"',
                'doi_files = ["data/interim/doi_queues/1467-9965_dois.txt", "data/interim/doi_queues/2214-6369_dois.txt"]',
                'email = "user@example.com"',
                "crossref_rows = 1000",
                "timeout_seconds = 60",
                'dois_dir = "data/interim/doi_queues"',
                'metadata_dir = "outputs/metadata"',
                'pdfs_dir = "outputs/pdfs"',
            ]
        ),
        encoding="utf-8",
    )

    parsed_args = cli.parse_download_args([])
    parsed_args.config = config_path

    seen_batches: list[tuple[tuple[str, ...], str | None, str]] = []

    def fake_run_download_batch(
        dois: list[str],
        issn: str | None,
        config: object,
        progress_files: object | None = None,
        retry_error_dois: bool = False,
    ) -> int:
        assert progress_files is not None
        source_path = progress_files.source_path
        seen_batches.append((tuple(dois), issn, source_path.name))
        return 0 if "1467-9965" in source_path.name else 1

    monkeypatch.setattr(cli, "run_download_batch", fake_run_download_batch)

    exit_code = cli.run_download(parsed_args)

    assert exit_code == 1
    assert seen_batches == [
        (("10.1111/first",), "1467-9965", "1467-9965_dois.txt"),
        (("10.2222/second",), "2214-6369", "2214-6369_dois.txt"),
    ]


def test_run_download_continues_after_one_configured_doi_file_fails_to_load(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """One missing DOI queue file should not block later configured batches."""
    second_dois_file = (
        tmp_path / "data" / "interim" / "doi_queues" / "2214-6369_dois.txt"
    )
    second_dois_file.parent.mkdir(parents=True, exist_ok=True)
    second_dois_file.write_text("10.2222/second\n", encoding="utf-8")

    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                'base_url = "https://publisher.example/pdf"',
                'doi_files = ["data/interim/doi_queues/missing_dois.txt", "data/interim/doi_queues/2214-6369_dois.txt"]',
                'email = "user@example.com"',
                "crossref_rows = 1000",
                "timeout_seconds = 60",
                'dois_dir = "data/interim/doi_queues"',
                'metadata_dir = "outputs/metadata"',
                'pdfs_dir = "outputs/pdfs"',
            ]
        ),
        encoding="utf-8",
    )

    parsed_args = cli.parse_download_args([])
    parsed_args.config = config_path

    seen_sources: list[str] = []

    def fake_run_download_batch(
        dois: list[str],
        issn: str | None,
        config: object,
        progress_files: object | None = None,
        retry_error_dois: bool = False,
    ) -> int:
        assert progress_files is not None
        seen_sources.append(progress_files.source_path.name)
        return 0

    monkeypatch.setattr(cli, "run_download_batch", fake_run_download_batch)

    exit_code = cli.run_download(parsed_args)

    assert exit_code == 1
    assert seen_sources == ["2214-6369_dois.txt"]


def test_run_export_metadata_uses_configured_doi_file_list_in_order(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Config-provided DOI queue files should drive metadata export in order."""
    first_dois_file = (
        tmp_path / "data" / "interim" / "doi_queues" / "1467-9965_dois.txt"
    )
    second_dois_file = (
        tmp_path / "data" / "interim" / "doi_queues" / "2214-6369_dois.txt"
    )
    first_dois_file.parent.mkdir(parents=True, exist_ok=True)
    first_dois_file.write_text("10.1111/first\n", encoding="utf-8")
    second_dois_file.write_text("10.2222/second\n", encoding="utf-8")

    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                'base_url = "https://publisher.example/pdf"',
                'doi_files = ["data/interim/doi_queues/1467-9965_dois.txt", "data/interim/doi_queues/2214-6369_dois.txt"]',
                'email = "user@example.com"',
                "crossref_rows = 1000",
                "timeout_seconds = 60",
                'dois_dir = "data/interim/doi_queues"',
                'metadata_dir = "outputs/metadata"',
                'pdfs_dir = "outputs/pdfs"',
            ]
        ),
        encoding="utf-8",
    )

    parsed_args = cli.parse_export_metadata_args([])
    parsed_args.config = config_path

    seen_exports: list[tuple[tuple[str, ...], str, str]] = []

    def fake_export_metadata_from_dois(
        dois: list[str],
        output_csv_path: Path,
        email: str,
        timeout_seconds: int = 60,
        max_workers: int = 8,
        request_delay_seconds: float = 0.05,
    ) -> Path:
        seen_exports.append(
            (
                tuple(dois),
                output_csv_path.name,
                str(max_workers),
                str(request_delay_seconds),
            )
        )
        return output_csv_path

    monkeypatch.setattr(
        cli, "export_metadata_from_dois", fake_export_metadata_from_dois
    )

    exit_code = cli.run_export_metadata(parsed_args)

    assert exit_code == 0
    assert seen_exports == [
        (("10.1111/first",), "1467-9965_metadata.csv", "8", "0.05"),
        (("10.2222/second",), "2214-6369_metadata.csv", "8", "0.05"),
    ]


def test_run_export_metadata_rejects_output_csv_for_multiple_batches(
    tmp_path: Path,
) -> None:
    """A single explicit CSV path is ambiguous for multiple DOI queue files."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                'base_url = "https://publisher.example/pdf"',
                'doi_files = ["data/interim/doi_queues/1467-9965_dois.txt", "data/interim/doi_queues/2214-6369_dois.txt"]',
                'email = "user@example.com"',
                "crossref_rows = 1000",
                "timeout_seconds = 60",
                'dois_dir = "data/interim/doi_queues"',
                'metadata_dir = "outputs/metadata"',
                'pdfs_dir = "outputs/pdfs"',
            ]
        ),
        encoding="utf-8",
    )

    parsed_args = cli.parse_export_metadata_args(
        ["--output-csv", str(tmp_path / "metadata.csv")]
    )
    parsed_args.config = config_path

    try:
        cli.run_export_metadata(parsed_args)
    except SystemExit as exc:
        assert (
            str(exc)
            == "--output-csv can only be used when exactly one DOI queue file is exported."
        )
    else:  # pragma: no cover
        raise AssertionError("Expected SystemExit")
