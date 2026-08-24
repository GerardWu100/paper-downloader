"""Shared HTTP helpers and constants for the paper-downloader package.

All JSON-fetching in this codebase uses the same pattern: build a GET request,
read the response, decode UTF-8, and assert the result is a dict.  This module
owns that implementation once; each calling module wraps it with its own
signature and default headers or timeout.

It also owns the two values every HTTP caller needs: the package `User-Agent`
string and the `JsonObject` type alias for a decoded JSON object.
"""

from __future__ import annotations

import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_HTTP_USER_AGENT: str = "paper-downloader/0.1.0"
DEFAULT_REQUEST_TIMEOUT_SECONDS: int = 60

# Crossref and OpenAlex both answer an over-eager client with 429, and both
# recover on their own within a few seconds. Retrying those, plus server-side
# 5xx and transport errors, turns a throttled burst into a slow run instead of
# a page of blank results.
RETRYABLE_HTTP_STATUS_CODE: int = 429
FIRST_SERVER_ERROR_STATUS_CODE: int = 500
MAX_REQUEST_ATTEMPTS: int = 4
INITIAL_RETRY_DELAY_SECONDS: float = 1.0
RETRY_DELAY_GROWTH_FACTOR: float = 2.0
MAX_RETRY_DELAY_SECONDS: float = 30.0

JsonObject = dict[str, object]

# Process-wide contact address for the provider polite pools. It stays empty
# until the command-line layer loads the configured value, because this project
# must never send an address its operator did not supply.
_polite_pool_email: str = ""


def set_polite_pool_email(email: str) -> None:
    """Record the contact address sent to provider polite pools.

    Parameters
    ----------
    email:
        Operator-supplied contact address. An empty or whitespace-only value
        clears the setting, and requests then go out without any address.
    """
    global _polite_pool_email
    _polite_pool_email = email.strip()


def polite_pool_email() -> str:
    """Return the configured polite-pool contact address, or an empty string."""
    return _polite_pool_email


def _is_retryable_http_status(status_code: int) -> bool:
    """Return `True` when a status code is worth retrying after a pause."""
    if status_code == RETRYABLE_HTTP_STATUS_CODE:
        return True

    return status_code >= FIRST_SERVER_ERROR_STATUS_CODE


def _retry_after_seconds(error: HTTPError) -> float | None:
    """Read a `Retry-After` delay in seconds from one HTTP error response.

    Only the numeric-seconds form is honored. The HTTP-date form is ignored
    because both providers send seconds, and guessing at clock skew is worse
    than falling back to the caller's own backoff schedule.
    """
    raw_retry_after = error.headers.get("Retry-After") if error.headers else None

    if raw_retry_after is None:
        return None

    try:
        retry_after = float(raw_retry_after.strip())
    except ValueError:
        return None

    if retry_after < 0.0:
        return None

    return min(retry_after, MAX_RETRY_DELAY_SECONDS)


def fetch_json_payload(
    url: str,
    headers: dict[str, str] | None = None,
    timeout_seconds: int = DEFAULT_REQUEST_TIMEOUT_SECONDS,
) -> JsonObject:
    """Fetch one JSON object from an HTTP GET endpoint.

    Parameters
    ----------
    url:
        Fully qualified URL to fetch.
    headers:
        Optional request headers dict.  Common use: ``User-Agent`` and polite
        Crossref ``mailto`` headers.
    timeout_seconds:
        Socket read timeout.  Defaults to 60 seconds.

    Returns
    -------
    dict[str, object]
        Parsed JSON object.

    Raises
    ------
    ValueError
        When the response is valid JSON but not a JSON object.
    urllib.error.HTTPError
        When the server keeps returning an error status after
        ``MAX_REQUEST_ATTEMPTS`` tries, or returns a status that is not worth
        retrying.

    Notes
    -----
    Rate-limit (429), server-error (5xx), and transport failures are retried
    with exponential backoff, honoring a numeric ``Retry-After`` header when
    the server sends one.
    """
    request_headers = headers or {}
    request = Request(url, headers=request_headers, method="GET")
    retry_delay_seconds = INITIAL_RETRY_DELAY_SECONDS

    for attempt_number in range(1, MAX_REQUEST_ATTEMPTS + 1):
        is_last_attempt = attempt_number == MAX_REQUEST_ATTEMPTS

        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if is_last_attempt or not _is_retryable_http_status(error.code):
                raise

            wait_seconds = _retry_after_seconds(error)

            if wait_seconds is None:
                wait_seconds = retry_delay_seconds
        except (URLError, TimeoutError):
            if is_last_attempt:
                raise

            wait_seconds = retry_delay_seconds
        else:
            if not isinstance(payload, dict):
                raise ValueError(f"Expected JSON object from {url}")

            return payload

        time.sleep(wait_seconds)
        retry_delay_seconds = min(
            retry_delay_seconds * RETRY_DELAY_GROWTH_FACTOR,
            MAX_RETRY_DELAY_SECONDS,
        )

    # The loop either returns a payload or re-raises on its final attempt.
    raise RuntimeError(f"Exhausted retries without a result for {url}")


def extract_object_list(payload: JsonObject, field_name: str) -> list[JsonObject]:
    """Return one payload field as a list of JSON objects.

    Provider responses are untrusted, so a missing field, a non-list value, and
    non-object entries inside the list are all treated the same way: they are
    skipped rather than raised on.

    Parameters
    ----------
    payload:
        Decoded JSON object to read one field from.
    field_name:
        Key whose value should be a list of JSON objects.

    Returns
    -------
    list[dict[str, object]]
        The object entries of that field, in order. Empty when the field is
        absent or holds something other than a list.
    """
    raw_items = payload.get(field_name)

    if not isinstance(raw_items, list):
        return []

    return [raw_item for raw_item in raw_items if isinstance(raw_item, dict)]
