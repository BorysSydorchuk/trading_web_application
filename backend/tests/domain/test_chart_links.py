"""TradingView chart link rule (docs/api.md M2 "Journal save" → chart_links)."""

from __future__ import annotations

import pytest

from app.domain.chart_links import (
    MAX_URL_LENGTH,
    duplicate_link_indexes,
    is_valid_chart_url,
    link_identity,
    preview_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.tradingview.com/x/AbCd1234/",
        "https://www.tradingview.com/x/AbCd1234",
        "https://tradingview.com/x/AbCd1234/",
        "https://uk.tradingview.com/x/AbCd1234/",
        "HTTPS://WWW.TradingView.COM/x/AbCd1234/",
        "https://www.tradingview.com/x/AbCd1234/?utm=1",
        "https://www.tradingview.com/x/AbCd1234/#top",
        "https://www.tradingview.com/x/AbCd1234/?a=1&b=2#frag",
        "https://www.tradingview.com/chart",
        "https://www.tradingview.com/chart/",
        "https://www.tradingview.com/chart/Xy12ab/",
        "https://www.tradingview.com/chart/Xy12ab",
        "https://www.tradingview.com/chart/?symbol=OANDA:XAUUSD",
    ],
)
def test_valid_urls(url: str) -> None:
    assert is_valid_chart_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://www.tradingview.com/x/AbCd1234/",  # not https
        "https://www.tradingview.com.evil.com/x/AbCd1234/",
        "https://evil.com/x/AbCd1234/",
        "https://www.tradingview.com/x/",  # no id
        "https://www.tradingview.com/x/Ab-Cd/",  # id chars
        "https://www.tradingview.com/x/AbCd1234//",
        "https://www.tradingview.com/X/AbCd1234/",  # path literal is case-sensitive
        "https://www.tradingview.com/charts/",
        "https://www.tradingview.com/chart/Xy12ab/extra/",
        "https://www.tradingview.com",  # no slash/path
        "https://www.tradingview.com/",
        "https://www.tradingview.com/x/AbCd1234/ ",
        "https://www.tradingview.com/x/AbCd1234/\n",
        " https://www.tradingview.com/x/AbCd1234/",
        "https://www.tradingview.com/x/AbCd1234/?a b",
        "tradingview.com/x/AbCd1234/",
        "",
    ],
)
def test_invalid_urls(url: str) -> None:
    assert not is_valid_chart_url(url)


def test_url_length_limit() -> None:
    base = "https://www.tradingview.com/x/AbCd1234/?q="
    assert is_valid_chart_url(base + "a" * (MAX_URL_LENGTH - len(base)))
    assert not is_valid_chart_url(base + "a" * (MAX_URL_LENGTH - len(base) + 1))


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("https://www.tradingview.com/x/AbCd1234/", "https://www.tradingview.com/x/AbCd1234"),
        ("https://www.tradingview.com/x/AbCd1234/", "HTTPS://WWW.TRADINGVIEW.COM/x/AbCd1234/"),
        ("https://www.tradingview.com/x/AbCd1234/?a=1", "https://www.tradingview.com/x/AbCd1234#f"),
        ("https://www.tradingview.com/chart", "https://www.tradingview.com/chart/?symbol=X"),
    ],
)
def test_same_identity(a: str, b: str) -> None:
    assert link_identity(a) == link_identity(b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        # Snapshot ids are case-sensitive.
        ("https://www.tradingview.com/x/AbCd1234/", "https://www.tradingview.com/x/abcd1234/"),
        # Different hosts stay different.
        ("https://www.tradingview.com/x/AbCd1234/", "https://tradingview.com/x/AbCd1234/"),
        ("https://www.tradingview.com/chart/", "https://www.tradingview.com/chart/Xy12ab/"),
    ],
)
def test_different_identity(a: str, b: str) -> None:
    assert link_identity(a) != link_identity(b)


def test_identity_shape() -> None:
    assert link_identity("HTTPS://WWW.TradingView.com/x/AbCd1234?x#y") == (
        "https://www.tradingview.com/x/AbCd1234/"
    )


def test_duplicate_indexes_report_later_items() -> None:
    urls = [
        "https://www.tradingview.com/x/AbCd1234/",
        "https://www.tradingview.com/x/Other1/",
        "https://www.tradingview.com/x/AbCd1234",
        "https://www.tradingview.com/x/AbCd1234/?again",
    ]
    assert duplicate_link_indexes(urls) == [2, 3]
    assert duplicate_link_indexes(urls[:2]) == []


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://www.tradingview.com/x/AbCd1234/",
            "https://s3.tradingview.com/snapshots/a/AbCd1234.png",
        ),
        (
            "https://tradingview.com/x/Zq9/?utm=1#f",
            "https://s3.tradingview.com/snapshots/z/Zq9.png",
        ),
        ("https://www.tradingview.com/x/9abc", "https://s3.tradingview.com/snapshots/9/9abc.png"),
        ("https://www.tradingview.com/chart/Xy12ab/", None),
        ("https://www.tradingview.com/chart", None),
        ("not a link", None),
    ],
)
def test_preview_url(url: str, expected: str | None) -> None:
    assert preview_url(url) == expected
