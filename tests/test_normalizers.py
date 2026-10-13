from __future__ import annotations

from datetime import datetime, timezone

from btcpoly.ingestion.agent_reach.normalizers import (
    coerce_items,
    normalize_github,
    normalize_rss_entry,
    normalize_web_page,
    normalize_youtube,
    normalize_v2ex,
)


def test_youtube_dump_json() -> None:
    post = normalize_youtube(
        {
            "id": "dQw4w9WgXcQ",
            "title": "Bitcoin news today",
            "uploader": "CryptoDesk",
            "timestamp": 1_777_000_000,
            "view_count": 12_345,
            "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        }
    )
    assert post.platform == "youtube"
    assert post.post_id == "dQw4w9WgXcQ"
    assert post.author == "CryptoDesk"
    assert post.event_ts.tzinfo == timezone.utc
    assert post.views == 12345
    assert post.url and "youtube" in post.url


def test_youtube_upload_date_yyyymmdd() -> None:
    post = normalize_youtube(
        {
            "id": "abc123",
            "title": "Bitcoin update",
            "uploader": "Davinci Jeremie",
            "upload_date": "20260820",
            "webpage_url": "https://www.youtube.com/watch?v=abc123",
        }
    )
    assert post.event_ts.year == 2026
    assert post.event_ts.month == 8
    assert post.event_ts.day == 20
    assert post.author == "Davinci Jeremie"


def test_github_search_json() -> None:
    post = normalize_github(
        {
            "fullName": "bitcoin/bitcoin",
            "url": "https://github.com/bitcoin/bitcoin",
            "description": "Bitcoin Core",
            "updatedAt": "2026-08-24T20:00:00Z",
            "owner": {"login": "bitcoin"},
        }
    )
    assert post.platform == "github"
    assert post.post_id == "bitcoin/bitcoin"
    assert post.author == "bitcoin"
    assert post.event_ts.year == 2026


def test_v2ex_json() -> None:
    post = normalize_v2ex(
        {
            "id": 99,
            "title": "Bitcoin ETF",
            "url": "https://www.v2ex.com/t/99",
            "created": 1_777_000_000,
            "content": "discuss",
            "replies": 4,
            "member": {"username": "sat"},
        }
    )
    assert post.platform == "v2ex"
    assert post.post_id == "99"
    assert post.author == "sat"
    assert post.replies == 4


def test_rss_entry() -> None:
    post = normalize_rss_entry(
        {
            "id": "https://example.com/btc-1",
            "title": "BTC jumps",
            "link": "https://example.com/btc-1",
            "published": "2026-08-24T20:00:00Z",
            "author": "wire",
        },
        "https://example.com/feed",
    )
    assert post is not None
    assert post.platform == "rss"
    assert post.post_id == "https://example.com/btc-1"
    assert post.event_ts.tzinfo == timezone.utc


def test_rss_rfc2822_and_struct_time() -> None:
    import time

    parsed = time.struct_time((2026, 8, 25, 22, 35, 52, 1, 237, 0))
    post = normalize_rss_entry(
        {
            "id": "https://news.bitcoin.com/?p=1",
            "title": "Bitcoin nears $80,000",
            "link": "https://news.bitcoin.com/a",
            "published": "Tue, 25 Aug 2026 22:35:52 +0000",
            "published_parsed": parsed,
        },
        "https://news.bitcoin.com/feed/",
    )
    assert post is not None
    assert post.event_ts == datetime(2026, 8, 25, 22, 35, 52, tzinfo=timezone.utc)


def test_rss_missing_date_returns_none() -> None:
    assert (
        normalize_rss_entry(
            {"id": "x", "title": "Bitcoin", "link": "https://example.com/x"},
            "https://example.com/feed",
        )
        is None
    )


def test_web_page() -> None:
    post = normalize_web_page("https://www.coindesk.com/", "# Bitcoin\nhello")
    assert post.platform == "web"
    assert post.text and "Bitcoin" in post.text
    assert post.event_ts.tzinfo == timezone.utc


def test_coerce_nested_items() -> None:
    items = coerce_items({"data": [{"id": 1}, {"id": 2}]})
    assert len(items) == 2
