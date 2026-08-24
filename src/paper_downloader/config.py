"""Application configuration loading and validation.

The command-line layer should parse arguments and orchestrate workflows. This
module owns TOML loading, local `.env` loading, path resolution, base URL
normalization, and boundary validation for values that later drive network and
filesystem work.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import tomllib

ROOT_DIR: Path = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH: Path = ROOT_DIR / "config.toml"
DEFAULT_ENV_PATH: Path = ROOT_DIR / ".env"
# Unset by default. Operators supply their own address; the project never
# invents one on their behalf.
DEFAULT_POLITE_POOL_EMAIL: str = ""
REMOVED_BROWSER_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "use_browser",
        "browser_headless",
        "browser_executable_path",
    }
)


@dataclass(frozen=True)
class AppConfig:
    """Resolved application configuration."""

    base_urls: tuple[str, ...]
    doi_worklist_files: tuple[Path, ...]
    email: str
    crossref_rows: int
    timeout_seconds: int
    dois_dir: Path
    metadata_dir: Path
    pdfs_dir: Path
    inter_download_sleep_seconds: float


def load_env_file(env_path: Path) -> dict[str, str]:
    """Load simple `KEY=VALUE` settings from a local `.env` file."""
    if not env_path.exists():
        return {}

    env_values: dict[str, str] = {}

    with env_path.open("r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            stripped_line = raw_line.strip()

            if not stripped_line:
                continue

            if stripped_line.startswith("#"):
                continue

            if stripped_line.startswith("export "):
                stripped_line = stripped_line.removeprefix("export ").lstrip()

            key, separator, value = stripped_line.partition("=")

            if not separator:
                continue

            normalized_key = key.strip()
            normalized_value = value.strip().strip('"').strip("'")
            env_values[normalized_key] = normalized_value

    return env_values


def normalize_base_url(raw_value: str) -> str:
    """Normalize one DOI base URL into a consistent canonical form."""
    stripped_value = raw_value.strip()

    if not stripped_value:
        return ""

    candidate_url = (
        stripped_value if "://" in stripped_value else f"https://{stripped_value}"
    )
    parsed_url = urlsplit(candidate_url)
    normalized_hostname = parsed_url.hostname

    if not parsed_url.netloc or normalized_hostname is None:
        return ""

    normalized_userinfo = ""

    if parsed_url.username is not None:
        normalized_userinfo = parsed_url.username

        if parsed_url.password is not None:
            normalized_userinfo = f"{normalized_userinfo}:{parsed_url.password}"

        normalized_userinfo = f"{normalized_userinfo}@"

    normalized_port = ""

    if parsed_url.port is not None:
        normalized_port = f":{parsed_url.port}"

    normalized_netloc = f"{normalized_userinfo}{normalized_hostname}{normalized_port}"
    normalized_path = parsed_url.path.rstrip("/")

    return urlunsplit(
        (
            parsed_url.scheme,
            normalized_netloc,
            normalized_path,
            parsed_url.query,
            parsed_url.fragment,
        )
    )


def parse_base_urls(
    raw_value: str | list[str] | tuple[str, ...] | None,
) -> tuple[str, ...]:
    """Parse one or more base URLs from CLI, config, or `.env` input."""
    if raw_value is None:
        return ()

    raw_chunks: list[str] = []

    if isinstance(raw_value, str):
        raw_chunks = raw_value.replace("\n", ",").split(",")
    else:
        for raw_item in raw_value:
            raw_chunks.extend(str(raw_item).replace("\n", ",").split(","))

    normalized_urls: list[str] = []
    seen_urls: set[str] = set()

    for raw_chunk in raw_chunks:
        normalized_url = normalize_base_url(raw_chunk)

        if not normalized_url:
            continue

        if normalized_url in seen_urls:
            continue

        seen_urls.add(normalized_url)
        normalized_urls.append(normalized_url)

    return tuple(normalized_urls)


def _resolve_relative_path(config_path: Path, raw_path: str) -> Path:
    """Resolve one config path relative to the config file directory."""
    candidate_path = Path(raw_path).expanduser()

    if candidate_path.is_absolute():
        return candidate_path.resolve()

    return (config_path.parent / candidate_path).resolve()


def _parse_positive_integer(raw_value: object, setting_name: str) -> int:
    """Parse one positive integer setting from TOML."""
    parsed_value = int(raw_value)

    if parsed_value <= 0:
        raise ValueError(f"{setting_name} must be positive.")

    return parsed_value


def _parse_non_negative_float(raw_value: object, setting_name: str) -> float:
    """Parse one non-negative floating-point setting from TOML."""
    parsed_value = float(raw_value)

    if parsed_value < 0.0:
        raise ValueError(f"{setting_name} must be non-negative.")

    return parsed_value


def _validate_config_directory(setting_name: str, resolved_dir: Path) -> None:
    """Validate that a configured directory does not collide with a file."""
    if resolved_dir.exists() and not resolved_dir.is_dir():
        raise ValueError(
            f"{setting_name} resolves to an existing file: {resolved_dir}. "
            "It must be a directory."
        )


def _resolve_configured_base_urls(
    raw_config: dict[str, object],
    env_values: dict[str, str],
) -> tuple[str, ...]:
    """Resolve base URLs with `.env` taking priority over `config.toml`."""
    config_base_urls = parse_base_urls(str(raw_config.get("base_url", "")).strip())
    env_base_urls = parse_base_urls(env_values.get("PAPER_DOWNLOADER_BASE_URLS", ""))
    return env_base_urls or config_base_urls


def _resolve_configured_email(
    raw_config: dict[str, object],
    env_values: dict[str, str],
) -> str:
    """Resolve the polite-pool contact address, with `.env` taking priority.

    The default is an empty string. Crossref and OpenAlex both treat a contact
    address as an identity claim, so this project never substitutes a
    placeholder: an unset address means requests go out anonymously, and DOI
    collection refuses to run at all.

    Parameters
    ----------
    raw_config:
        Decoded `config.toml` mapping.
    env_values:
        Values loaded from a local `.env` file, which override the TOML value.

    Returns
    -------
    str
        Trimmed contact address, or an empty string when none is configured.
    """
    return str(
        env_values.get(
            "PAPER_DOWNLOADER_EMAIL",
            str(raw_config.get("email", DEFAULT_POLITE_POOL_EMAIL)).strip(),
        )
    ).strip()


def _resolve_output_directories(
    config_path: Path,
    raw_config: dict[str, object],
) -> tuple[Path, Path, Path]:
    """Resolve the configured output directories relative to the config file."""
    dois_dir = _resolve_relative_path(
        config_path,
        str(raw_config.get("dois_dir", "data/interim/doi_queues")),
    )
    metadata_dir = _resolve_relative_path(
        config_path,
        str(raw_config.get("metadata_dir", "outputs/metadata")),
    )
    pdfs_dir = _resolve_relative_path(
        config_path,
        str(raw_config.get("pdfs_dir", "outputs/pdfs")),
    )

    return dois_dir, metadata_dir, pdfs_dir


def _parse_configured_doi_files(
    config_path: Path,
    raw_doi_file: object,
    raw_doi_files: object,
) -> tuple[Path, ...]:
    """Resolve one or more configured DOI queue files."""
    configured_entries: list[str] = []

    if raw_doi_file != "":
        if not isinstance(raw_doi_file, str):
            raise ValueError("doi_file must be a string.")

        normalized_doi_file = raw_doi_file.strip()

        if normalized_doi_file:
            configured_entries.append(normalized_doi_file)

    if isinstance(raw_doi_files, list):
        for raw_entry in raw_doi_files:
            if not isinstance(raw_entry, str):
                raise ValueError("doi_files entries must be strings.")

            normalized_entry = raw_entry.strip()

            if normalized_entry:
                configured_entries.append(normalized_entry)
    elif raw_doi_files != []:
        raise ValueError("doi_files must be an array of strings.")

    resolved_paths: list[Path] = []
    seen_paths: set[Path] = set()

    for configured_entry in configured_entries:
        resolved_path = _resolve_relative_path(config_path, configured_entry)

        if resolved_path in seen_paths:
            continue

        seen_paths.add(resolved_path)
        resolved_paths.append(resolved_path)

    return tuple(resolved_paths)


def load_config(config_path: Path) -> AppConfig:
    """Load application settings from one TOML file."""
    with config_path.open("rb") as config_file:
        raw_config = tomllib.load(config_file)

    # Fail fast on stale browser settings so old config files do not imply a
    # download mode this project no longer supports.
    removed_browser_keys = sorted(REMOVED_BROWSER_CONFIG_KEYS.intersection(raw_config))

    if removed_browser_keys:
        removed_key_list = ", ".join(removed_browser_keys)
        raise ValueError(
            "Browser download mode has been removed. Delete these config keys: "
            f"{removed_key_list}."
        )

    # Environment values are the operator override layer, so resolve them once
    # and reuse the same map for the URL and email settings below.
    env_values = load_env_file(config_path.parent / DEFAULT_ENV_PATH.name)
    resolved_base_urls = _resolve_configured_base_urls(raw_config, env_values)
    configured_doi_files = _parse_configured_doi_files(
        config_path=config_path,
        raw_doi_file=raw_config.get("doi_file", ""),
        raw_doi_files=raw_config.get("doi_files", []),
    )
    crossref_rows = _parse_positive_integer(
        raw_config.get("crossref_rows", 1000),
        "crossref_rows",
    )
    timeout_seconds = _parse_positive_integer(
        raw_config.get("timeout_seconds", 60),
        "timeout_seconds",
    )
    inter_download_sleep_seconds = _parse_non_negative_float(
        raw_config.get("inter_download_sleep_seconds", 3.0),
        "inter_download_sleep_seconds",
    )
    email = _resolve_configured_email(raw_config, env_values)
    # Output paths stay relative to the config file so the project can be run
    # from any working directory without losing the intended artifact layout.
    dois_dir, metadata_dir, pdfs_dir = _resolve_output_directories(
        config_path,
        raw_config,
    )

    _validate_config_directory("dois_dir", dois_dir)
    _validate_config_directory("metadata_dir", metadata_dir)
    _validate_config_directory("pdfs_dir", pdfs_dir)

    return AppConfig(
        base_urls=resolved_base_urls,
        doi_worklist_files=configured_doi_files,
        email=email,
        crossref_rows=crossref_rows,
        timeout_seconds=timeout_seconds,
        dois_dir=dois_dir,
        metadata_dir=metadata_dir,
        pdfs_dir=pdfs_dir,
        inter_download_sleep_seconds=inter_download_sleep_seconds,
    )
