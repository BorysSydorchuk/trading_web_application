"""TradingView chart links (docs/api.md M2 "Journal save" → chart_links). Pure functions.

The frontend uses the same regex and duplicate rule. Scheme and host are case-insensitive
(lower-cased before matching); the path, including the snapshot id, is case-sensitive.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from urllib.parse import urlsplit

MAX_URL_LENGTH = 500
MAX_LINKS = 10

# docs/api.md, verbatim. Applied with fullmatch after lower-casing scheme + host.
CHART_URL_PATTERN = re.compile(
    r"^https://([a-z0-9-]+\.)?tradingview\.com/"
    r"(x/[A-Za-z0-9]+/?|chart(/([A-Za-z0-9]+/?)?)?)"
    r"(\?[^#\s]*)?(#\S*)?$"
)
_SCHEME_HOST = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://[^/?#\s]*)(.*)", re.DOTALL)
_SNAPSHOT_PATH = re.compile(r"/x/([A-Za-z0-9]+)/?")
PREVIEW_TEMPLATE = "https://s3.tradingview.com/snapshots/{first}/{id}.png"


def _lower_scheme_host(url: str) -> str:
    match = _SCHEME_HOST.fullmatch(url)
    if match is None:
        return url
    return match.group(1).lower() + match.group(2)


def is_valid_chart_url(url: str) -> bool:
    if not url or len(url) > MAX_URL_LENGTH:
        return False
    return CHART_URL_PATTERN.fullmatch(_lower_scheme_host(url)) is not None


def link_identity(url: str) -> str:
    """Duplicate key: lower-case scheme + host, path with exactly one trailing slash;
    query and fragment ignored."""
    parts = urlsplit(url)
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}{parts.path.rstrip('/')}/"


def duplicate_link_indexes(urls: Sequence[str]) -> list[int]:
    """Indexes of links that repeat an earlier one (the first occurrence is not reported)."""
    seen: set[str] = set()
    dupes: list[int] = []
    for i, url in enumerate(urls):
        identity = link_identity(url)
        if identity in seen:
            dupes.append(i)
        seen.add(identity)
    return dupes


def preview_url(url: str) -> str | None:
    """Snapshot image for a `/x/<id>` link; None for chart links and invalid URLs."""
    if not is_valid_chart_url(url):
        return None
    match = _SNAPSHOT_PATH.fullmatch(urlsplit(url).path)
    if match is None:
        return None
    snapshot = match.group(1)
    return PREVIEW_TEMPLATE.format(first=snapshot[0].lower(), id=snapshot)
