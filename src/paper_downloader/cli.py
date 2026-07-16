"""Command-line entrypoints for `paper-downloader`.

The project now follows the same two-step workflow style as
`education-scraper`:

1. Build a DOI queue file from one ISSN.
2. Download PDFs from that DOI queue file.

The top-level CLI exposes both steps as subcommands, and the project also
installs separate entrypoints for each step.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .audit import build_download_audit_summary, format_download_audit_summary
from .config import (
    DEFAULT_CONFIG_PATH,
    AppConfig,
    load_config,
    parse_base_urls,
)
from .doi_sources import fetch_all_dois_for_issn, write_doi_file
from .downloader import DownloadConfig, run_download_batch
from .metadata.export import (
    DEFAULT_METADATA_MAX_WORKERS,
    DEFAULT_REQUEST_DELAY_SECONDS,
    build_default_metadata_csv_path,
    export_metadata_from_dois,
)
from .progress import (
    build_batch_progress_files,
    derive_issn_from_dois_file,
    load_dois_from_file,
)


def add_shared_config_argument(parser: argparse.ArgumentParser) -> None:
    """Add the shared config-path argument to one parser."""
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to config.toml.",
    )


def _add_fetch_dois_arguments(parser: argparse.ArgumentParser) -> None:
    """Add fetch-dois arguments to one parser."""
    parser.add_argument(
        "--issn",
        required=True,
        help="Journal ISSN used for DOI collection.",
    )
    add_shared_config_argument(parser)
    parser.add_argument("--email", help="Override the Crossref polite-pool email.")
    parser.add_argument(
        "--rows",
        type=int,
        help="Override Crossref page size for DOI collection.",
    )


def _add_download_arguments(parser: argparse.ArgumentParser) -> None:
    """Add download arguments to one parser."""
    parser.add_argument("--doi", help="Download exactly one DOI.")
    parser.add_argument("--dois-file", type=Path, help="Existing DOI queue file.")
    add_shared_config_argument(parser)
    parser.add_argument(
        "--base-url",
        action="append",
        help="Override one DOI download base URL. Pass multiple times to try multiple URLs.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--retry-error-dois",
        action="store_true",
        help="Retry DOI values already recorded in the error ledger.",
    )


def _add_export_metadata_arguments(parser: argparse.ArgumentParser) -> None:
    """Add export-metadata arguments to one parser."""
    parser.add_argument(
        "--dois-file",
        type=Path,
        help="Existing DOI queue file.",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        help="Optional output CSV path. Defaults beside the DOI file.",
    )
    add_shared_config_argument(parser)
    parser.add_argument("--email", help="Override the Crossref polite-pool email.")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=DEFAULT_METADATA_MAX_WORKERS,
        help=(
            "Maximum parallel metadata lookups. "
            f"Defaults to {DEFAULT_METADATA_MAX_WORKERS}."
        ),
    )
    parser.add_argument(
        "--request-delay-seconds",
        type=float,
        default=DEFAULT_REQUEST_DELAY_SECONDS,
        help=(
            "Minimum delay between metadata request starts to the same API host. "
            f"Defaults to {DEFAULT_REQUEST_DELAY_SECONDS}."
        ),
    )


def _add_audit_arguments(parser: argparse.ArgumentParser) -> None:
    """Add download-audit arguments to one parser."""
    parser.add_argument(
        "--dois-file",
        type=Path,
        required=True,
        help="Existing DOI queue file to audit.",
    )
    add_shared_config_argument(parser)


def build_fetch_dois_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> argparse.ArgumentParser:
    """Build the DOI-collection subcommand parser."""
    parser = subparsers.add_parser(
        "fetch-dois",
        help=(
            "Fetch all DOIs for one ISSN and write "
            "data/interim/doi_queues/<issn>_dois.txt."
        ),
    )
    _add_fetch_dois_arguments(parser)
    return parser


def build_download_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> argparse.ArgumentParser:
    """Build the PDF-download subcommand parser."""
    parser = subparsers.add_parser(
        "download",
        help="Download PDFs from one DOI text file or a single DOI.",
    )
    _add_download_arguments(parser)
    return parser


def build_export_metadata_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> argparse.ArgumentParser:
    """Build the metadata-export subcommand parser."""
    parser = subparsers.add_parser(
        "export-metadata",
        help="Export metadata from one DOI text file into a CSV file.",
    )
    _add_export_metadata_arguments(parser)
    return parser


def build_audit_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> argparse.ArgumentParser:
    """Build the download-audit subcommand parser."""
    parser = subparsers.add_parser(
        "audit",
        help="Summarize local DOI queue, ledger, and PDF completion state.",
    )
    _add_audit_arguments(parser)
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Two-step DOI workflow: fetch DOI files from an ISSN, then download "
            "PDFs from the DOI text file."
        )
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True

    build_fetch_dois_parser(subparsers)
    build_download_parser(subparsers)
    build_export_metadata_parser(subparsers)
    build_audit_parser(subparsers)

    parsed_args = parser.parse_args(argv)
    return parsed_args


def parse_fetch_dois_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse arguments for the DOI-collection entrypoint."""
    parser = argparse.ArgumentParser(
        description="Fetch all article DOIs for one ISSN into a DOI text file."
    )
    _add_fetch_dois_arguments(parser)
    return parser.parse_args(argv)


def parse_download_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse arguments for the download entrypoint."""
    parser = argparse.ArgumentParser(
        description="Download PDFs from one DOI text file or a single DOI."
    )
    _add_download_arguments(parser)
    return parser.parse_args(argv)


def parse_export_metadata_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse arguments for the metadata-export entrypoint."""
    parser = argparse.ArgumentParser(
        description="Export article metadata from one DOI text file into CSV."
    )
    _add_export_metadata_arguments(parser)
    return parser.parse_args(argv)


def _cli_or_config(
    parsed_args: argparse.Namespace,
    attr: str,
    config_value: object,
) -> object:
    """Return the CLI override when present, otherwise the config-file value."""
    cli_value = getattr(parsed_args, attr, None)
    return cli_value if cli_value is not None else config_value


def _resolve_configured_doi_files(
    parsed_args: argparse.Namespace,
    app_config: AppConfig,
) -> tuple[Path, ...]:
    """Return DOI queue paths from ``--dois-file`` or ``config.toml``."""
    if parsed_args.dois_file is not None:
        return (parsed_args.dois_file.resolve(),)

    return app_config.doi_worklist_files


def merge_config(parsed_args: argparse.Namespace, file_config: AppConfig) -> AppConfig:
    """Merge CLI overrides into the TOML configuration."""
    cli_base_url = getattr(parsed_args, "base_url", None)
    cli_email = getattr(parsed_args, "email", None)

    return AppConfig(
        base_urls=parse_base_urls(cli_base_url)
        if cli_base_url is not None
        else file_config.base_urls,
        doi_worklist_files=file_config.doi_worklist_files,
        email=(cli_email or file_config.email).strip(),
        crossref_rows=_cli_or_config(parsed_args, "rows", file_config.crossref_rows),
        timeout_seconds=_cli_or_config(
            parsed_args, "timeout_seconds", file_config.timeout_seconds
        ),
        dois_dir=file_config.dois_dir,
        metadata_dir=file_config.metadata_dir,
        pdfs_dir=file_config.pdfs_dir,
        inter_download_sleep_seconds=file_config.inter_download_sleep_seconds,
    )


def build_download_config(app_config: AppConfig) -> DownloadConfig:
    """Convert application settings into runtime download settings."""
    return DownloadConfig(
        base_urls=app_config.base_urls,
        pdf_root_dir=app_config.pdfs_dir,
        timeout_seconds=app_config.timeout_seconds,
        inter_download_sleep_seconds=app_config.inter_download_sleep_seconds,
    )


def run_fetch_dois(parsed_args: argparse.Namespace) -> int:
    """Fetch one DOI queue file from one ISSN."""
    file_config = load_config(parsed_args.config.resolve())
    app_config = merge_config(parsed_args, file_config)
    issn = parsed_args.issn.strip()

    if not app_config.email:
        raise SystemExit("A non-empty email is required for Crossref DOI collection.")

    doi_list = fetch_all_dois_for_issn(
        issn=issn,
        email=app_config.email,
        rows=app_config.crossref_rows,
    )
    dois_file_path = write_doi_file(app_config.dois_dir, issn, doi_list)
    print(f"Saved {len(doi_list)} DOIs to {dois_file_path}")
    return 0


def run_download(parsed_args: argparse.Namespace) -> int:
    """Download PDFs from an existing DOI worklist."""
    file_config = load_config(parsed_args.config.resolve())
    app_config = merge_config(parsed_args, file_config)

    if not app_config.base_urls:
        raise SystemExit(
            "At least one base URL must be set in .env, config.toml, or via --base-url"
        )

    download_config = build_download_config(app_config)

    if parsed_args.doi is not None:
        return run_download_batch(
            dois=[parsed_args.doi.strip()],
            issn=None,
            config=download_config,
            progress_files=None,
            retry_error_dois=parsed_args.retry_error_dois,
        )

    configured_doi_files = _resolve_configured_doi_files(parsed_args, app_config)

    if not configured_doi_files:
        raise SystemExit(
            "Download requires --doi, --dois-file, or config.toml doi_file/doi_files."
        )

    overall_exit_code = 0
    total_batches = len(configured_doi_files)

    for batch_index, dois_file_path in enumerate(configured_doi_files, start=1):
        print(f"[{batch_index}/{total_batches}] starting {dois_file_path}")

        try:
            # Load each queue independently so one bad path does not stop the run.
            dois = load_dois_from_file(dois_file_path)
            issn = derive_issn_from_dois_file(dois_file_path)
            progress_files = build_batch_progress_files(dois_file_path)
        except Exception as exc:  # noqa: BLE001
            overall_exit_code = 1
            print(
                f"[{batch_index}/{total_batches}] failed to prepare "
                f"{dois_file_path}: {exc}"
            )
            continue

        batch_exit_code = run_download_batch(
            dois=dois,
            issn=issn,
            config=download_config,
            progress_files=progress_files,
            retry_error_dois=parsed_args.retry_error_dois,
        )
        overall_exit_code = max(overall_exit_code, batch_exit_code)

    return overall_exit_code


def run_export_metadata(parsed_args: argparse.Namespace) -> int:
    """Export CSV metadata from an existing DOI worklist."""
    file_config = load_config(parsed_args.config.resolve())
    app_config = merge_config(parsed_args, file_config)
    configured_doi_files = _resolve_configured_doi_files(parsed_args, app_config)

    if not configured_doi_files:
        raise SystemExit(
            "Metadata export requires --dois-file or config.toml doi_file/doi_files."
        )

    if parsed_args.output_csv is not None and len(configured_doi_files) != 1:
        raise SystemExit(
            "--output-csv can only be used when exactly one DOI queue file is exported."
        )

    overall_exit_code = 0
    total_batches = len(configured_doi_files)

    for batch_index, dois_file_path in enumerate(configured_doi_files, start=1):
        print(f"[{batch_index}/{total_batches}] starting metadata {dois_file_path}")

        try:
            dois = load_dois_from_file(dois_file_path)
            output_csv_path = (
                parsed_args.output_csv.resolve()
                if parsed_args.output_csv is not None
                else build_default_metadata_csv_path(
                    dois_file_path=dois_file_path,
                    metadata_dir=app_config.metadata_dir,
                )
            )
            written_csv_path = export_metadata_from_dois(
                dois=dois,
                output_csv_path=output_csv_path,
                email=app_config.email,
                timeout_seconds=app_config.timeout_seconds,
                max_workers=parsed_args.max_workers,
                request_delay_seconds=parsed_args.request_delay_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            overall_exit_code = 1
            print(
                f"[{batch_index}/{total_batches}] failed metadata "
                f"{dois_file_path}: {exc}"
            )
            continue

        print(f"Saved metadata for {len(dois)} DOIs to {written_csv_path}")

    return overall_exit_code


def run_audit(parsed_args: argparse.Namespace) -> int:
    """Print a no-network local audit summary for one DOI queue."""
    file_config = load_config(parsed_args.config.resolve())
    summary = build_download_audit_summary(
        dois_file_path=parsed_args.dois_file.resolve(),
        pdf_root_dir=file_config.pdfs_dir,
    )
    print(format_download_audit_summary(summary))
    return 0


def fetch_dois_entrypoint(argv: list[str] | None = None) -> int:
    """Run the DOI-collection entrypoint."""
    parsed_args = parse_fetch_dois_args(argv)
    return run_fetch_dois(parsed_args)


def download_entrypoint(argv: list[str] | None = None) -> int:
    """Run the download entrypoint."""
    parsed_args = parse_download_args(argv)
    return run_download(parsed_args)


def export_metadata_entrypoint(argv: list[str] | None = None) -> int:
    """Run the metadata-export entrypoint."""
    parsed_args = parse_export_metadata_args(argv)
    return run_export_metadata(parsed_args)


def main(argv: list[str] | None = None) -> int:
    """Run the top-level workflow CLI with explicit subcommands."""
    parsed_args = parse_args(argv)

    if parsed_args.command == "fetch-dois":
        return run_fetch_dois(parsed_args)

    if parsed_args.command == "download":
        return run_download(parsed_args)

    if parsed_args.command == "export-metadata":
        return run_export_metadata(parsed_args)

    if parsed_args.command == "audit":
        return run_audit(parsed_args)

    raise SystemExit(f"Unsupported command: {parsed_args.command}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
