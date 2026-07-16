"""Shared HTTP helpers for the paper-downloader package.

All JSON-fetching in this codebase uses the same pattern: build a GET request,
read the response, decode UTF-8, and assert the result is a dict.  This module
owns that implementation once; each calling module wraps it with its own
signature and default headers or timeout.
"""

from __future__ import annotations

import json
from urllib.request import Request, urlopen

JsonObject = dict[str, object]


def fetch_json_payload(
    url: str,
    headers: dict[str, str] | None = None,
    timeout_seconds: int = 60,
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
