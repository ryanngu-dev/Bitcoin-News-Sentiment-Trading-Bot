from __future__ import annotations

from datetime import datetime, timezone

from btcpoly.monitoring.feed import (
    format_event_time,
    headline_from_post,
    headline_key,
    render_source_line,
    sort_headlines,
)


def test_youtube_uses_video_title_and_red_style() -> None:
    headline = headline_from_post(
        "youtube",
        "ignored body",
        author="CryptoDesk",
        url="https://www.youtube.com/watch?v=abc",
        raw_json={"title": "Bitcoin weekly recap"},
        event_ts=datetime(2026, 8, 25, 18, 30, tzinfo=timezone.utc),
    )
    assert headline.title == "Bitcoin weekly recap"
    assert headline.author == "CryptoDesk"
    line = render_source_line(headline)
    assert "YOUTUBE" in line.plain
    assert "CryptoDesk" in line.plain
    assert "Bitcoin weekly recap" in line.plain
    assert "open" in line.plain
    assert "11:30PST" in line.plain.replace(" ", "") or "11:30 PST" in line.plain or "Aug 25" in line.plain
    styles = " ".join(str(span.style) for span in line.spans)
    assert "bright_red" in styles
    assert any("link https://www.youtube.com/watch?v=abc" in str(span.style) for span in line.spans)


def test_twitter_builds_status_link() -> None:
    headline = headline_from_post(
        "twitter",
        "BTC pumping",
        author="saylor",
        raw_json={"id": "2092329038807289884", "title": ""},
        event_ts=datetime(2026, 8, 25, 19, 11, tzinfo=timezone.utc),
    )
    assert headline.url == "https://x.com/saylor/status/2092329038807289884"
    line = render_source_line(headline)
    assert "open" in line.plain
    assert any("link https://x.com/saylor/status/" in str(span.style) for span in line.spans)


def test_headline_key_prefers_url() -> None:
    headline = headline_from_post("rss", "BTC jumps", url="https://example.com/a")
    assert headline_key(headline) == "https://example.com/a"


def test_sort_headlines_by_event_time_not_platform() -> None:
    older = headline_from_post(
        "youtube",
        "old",
        author="A",
        event_ts=datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc),
        raw_json={"title": "old yt"},
    )
    newer = headline_from_post(
        "rss",
        "new",
        author="B",
        event_ts=datetime(2026, 8, 25, 20, 0, tzinfo=timezone.utc),
        raw_json={"title": "new rss"},
    )
    ordered = sort_headlines([older, newer], newest_first=False)
    assert ordered[0].platform == "youtube"
    assert ordered[1].platform == "rss"


def test_format_event_time() -> None:
    assert format_event_time(None) == "????"
    stamp = format_event_time(datetime(2026, 8, 25, 20, 55, tzinfo=timezone.utc))
    assert "13:55PST" in stamp.replace(" ", "") or "13:55 PST" in stamp
    assert "now" in stamp or "m" in stamp or "h" in stamp
