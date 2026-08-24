"""Tests for the shared HTTP layer: retry backoff and polite-pool contact."""

from __future__ import annotations

import io
import json
from typing import Any
from urllib.error import HTTPError, URLError

import pytest

from paper_downloader import _http


class FakeResponse:
    """Minimal stand-in for the object `urlopen` returns as a context manager."""

    def __init__(self, payload: dict[str, object]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exception_details: object) -> bool:
        return False

    def read(self) -> bytes:
        """Return the encoded JSON body."""
        return self._body


def build_http_error(status_code: int, retry_after: str | None = None) -> HTTPError:
    """Build one `HTTPError` with an optional `Retry-After` header."""
    headers: dict[str, str] = {}

    if retry_after is not None:
        headers["Retry-After"] = retry_after

    return HTTPError(
        url="https://api.example.org/works",
        code=status_code,
        msg="throttled",
        hdrs=headers,  # type: ignore[arg-type]
        fp=io.BytesIO(b""),
    )


@pytest.fixture(autouse=True)
def recorded_sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replace the retry sleep with a recorder so tests never actually wait."""
    sleeps: list[float] = []
    monkeypatch.setattr(_http.time, "sleep", sleeps.append)
    return sleeps


def install_fake_urlopen(
    monkeypatch: pytest.MonkeyPatch,
    outcomes: list[Any],
) -> list[str]:
    """Serve one queued outcome per `urlopen` call and record the URLs."""
    requested_urls: list[str] = []
    remaining_outcomes = list(outcomes)

    def fake_urlopen(request: Any, timeout: int) -> FakeResponse:
        requested_urls.append(request.full_url)
        outcome = remaining_outcomes.pop(0)

        if isinstance(outcome, Exception):
            raise outcome

        return outcome

    monkeypatch.setattr(_http, "urlopen", fake_urlopen)
    return requested_urls


def test_fetch_json_payload_retries_after_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
    recorded_sleeps: list[float],
) -> None:
    """A 429 should be retried instead of surfacing as a failed lookup."""
    requested_urls = install_fake_urlopen(
        monkeypatch,
        [build_http_error(429), FakeResponse({"ok": True})],
    )

    payload = _http.fetch_json_payload("https://api.example.org/works")

    assert payload == {"ok": True}
    assert len(requested_urls) == 2
    assert recorded_sleeps == [_http.INITIAL_RETRY_DELAY_SECONDS]


def test_fetch_json_payload_honors_retry_after_header(
    monkeypatch: pytest.MonkeyPatch,
    recorded_sleeps: list[float],
) -> None:
    """A numeric `Retry-After` should replace the default backoff delay."""
    install_fake_urlopen(
        monkeypatch,
        [build_http_error(429, retry_after="7"), FakeResponse({"ok": True})],
    )

    _http.fetch_json_payload("https://api.example.org/works")

    assert recorded_sleeps == [7.0]


def test_fetch_json_payload_retries_server_errors_with_growing_delay(
    monkeypatch: pytest.MonkeyPatch,
    recorded_sleeps: list[float],
) -> None:
    """Repeated 5xx responses should back off exponentially."""
    install_fake_urlopen(
        monkeypatch,
        [
            build_http_error(503),
            build_http_error(500),
            FakeResponse({"ok": True}),
        ],
    )

    _http.fetch_json_payload("https://api.example.org/works")

    assert recorded_sleeps == [
        _http.INITIAL_RETRY_DELAY_SECONDS,
        _http.INITIAL_RETRY_DELAY_SECONDS * _http.RETRY_DELAY_GROWTH_FACTOR,
    ]


def test_fetch_json_payload_retries_transport_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dropped connection should be retried like a throttle response."""
    install_fake_urlopen(
        monkeypatch,
        [URLError("connection reset"), FakeResponse({"ok": True})],
    )

    assert _http.fetch_json_payload("https://api.example.org/works") == {"ok": True}


def test_fetch_json_payload_does_not_retry_client_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 404 is a final answer, so it should be raised on the first attempt."""
    requested_urls = install_fake_urlopen(monkeypatch, [build_http_error(404)])

    with pytest.raises(HTTPError):
        _http.fetch_json_payload("https://api.example.org/works")

    assert len(requested_urls) == 1


def test_fetch_json_payload_gives_up_after_max_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persistent throttling should raise rather than loop forever."""
    requested_urls = install_fake_urlopen(
        monkeypatch,
        [build_http_error(429) for _ in range(_http.MAX_REQUEST_ATTEMPTS)],
    )

    with pytest.raises(HTTPError):
        _http.fetch_json_payload("https://api.example.org/works")

    assert len(requested_urls) == _http.MAX_REQUEST_ATTEMPTS


def test_polite_pool_email_defaults_to_unset() -> None:
    """No contact address should be sent until one is configured."""
    _http.set_polite_pool_email("")

    assert _http.polite_pool_email() == ""


def test_set_polite_pool_email_trims_whitespace() -> None:
    """A configured address should be stored without surrounding whitespace."""
    _http.set_polite_pool_email("  person@example.org  ")

    try:
        assert _http.polite_pool_email() == "person@example.org"
    finally:
        _http.set_polite_pool_email("")
