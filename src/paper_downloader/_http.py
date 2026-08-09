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
from urllib.request import Request, urlopen

DEFAULT_HTTP_USER_AGENT: str = "paper-downloader/0.1.0"
DEFAULT_REQUEST_TIMEOUT_SECONDS: int = 60

JsonObject = dict[str, object]


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
    """
    request_headers = headers or {}
    request = Request(url, headers=request_headers, method="GET")

    with urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object from {url}")

    return payload


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
