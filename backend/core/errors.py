"""User-facing wording for failures of outside data services.

Low-level network errors (e.g. "HTTPSConnectionPool(host=..., port=443): Max retries exceeded ...")
are logged in full on the server and replaced by a short, plain reason for the website.
Messages that OzoneGuard itself raises (RuntimeError / ValueError with a written explanation,
such as the NASA token messages) are passed through unchanged.
"""
from __future__ import annotations

import logging

import requests

log = logging.getLogger("ozoneguard.upstream")

_LOW_LEVEL_MARKERS = ("Pool(", "Errno", "Traceback", "Max retries", "object at 0x", "urllib3")


def describe_failure(exc: BaseException) -> str:
    """Short, plain-language reason why a call to an outside service failed."""
    log.warning("outside service failed: %r", exc)
    if isinstance(exc, requests.Timeout):
        return "the service did not respond in time. Please try again in a minute"
    if isinstance(exc, requests.ConnectionError):
        return "the service could not be reached. Check the internet connection and try again"
    if isinstance(exc, requests.HTTPError):
        code = getattr(getattr(exc, "response", None), "status_code", None)
        return f"the service returned an error (HTTP {code})" if code else "the service returned an error"
    if isinstance(exc, requests.RequestException):
        return "the request to the service failed"
    msg = str(exc).strip()
    if not msg or len(msg) > 400 or any(m in msg for m in _LOW_LEVEL_MARKERS):
        return "the service returned an unexpected response"
    return msg
