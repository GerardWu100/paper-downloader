"""Public exports for the paper-downloader package.

The package is intentionally small. The CLI module owns orchestration, while
the sibling modules split DOI collection, metadata export, naming, progress
tracking, and PDF download behavior.
"""

from .doi_sources import fetch_all_dois_for_issn, write_doi_file
from .downloader import DownloadConfig, build_doi_download_url, run_download_batch
from .metadata.export import MetadataRecord, export_metadata_from_dois
from .naming import build_target_pdf_filename, lookup_doi_metadata
from .progress import build_batch_progress_files, load_dois_from_file

__all__ = [
    "DownloadConfig",
    "MetadataRecord",
    "build_batch_progress_files",
    "build_doi_download_url",
    "build_target_pdf_filename",
    "export_metadata_from_dois",
    "fetch_all_dois_for_issn",
    "load_dois_from_file",
    "lookup_doi_metadata",
    "run_download_batch",
    "write_doi_file",
]
