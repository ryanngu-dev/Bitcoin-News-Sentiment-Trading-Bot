from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from btcpoly.ingestion.schema import RawPost
from btcpoly.timeutil import available_at, parse_ts, to_utc, utcnow


def test_naive_datetime_becomes_utc() -> None:
    naive = datetime(2026, 8, 24, 20, 0, 0)
    aware = to_utc(naive)
    assert aware.tzinfo == timezone.utc
    assert aware.hour == 20


def test_parse_iso_z_and_offset() -> None:
    z = parse_ts("2026-08-24T20:00:00Z")
    offset = parse_ts("2026-08-24T16:00:00-04:00")
    assert z == offset
    assert z.tzinfo == timezone.utc


def test_parse_unix_seconds_and_millis() -> None:
    seconds = parse_ts(1_777_000_000)
    millis = parse_ts(1_777_000_000_000)
    assert seconds == millis


def test_raw_post_normalizes_event_ts() -> None:
    post = RawPost(
        platform="twitter",
        post_id="1",
        event_ts="2026-08-24T20:00:00Z",
        text="bitcoin",
    )
    assert post.event_ts.tzinfo == timezone.utc
    assert post.ingested_at.tzinfo == timezone.utc


def test_as_of_rejects_future_ingest() -> None:
    event = datetime(2026, 8, 24, 20, 0, tzinfo=timezone.utc)
    ingest = event + timedelta(minutes=2)
    as_of = event + timedelta(minutes=1)
    assert available_at(event, ingest, as_of) is False
    assert available_at(event, event, as_of) is True


def test_parse_ts_rejects_empty() -> None:
    with pytest.raises(ValueError):
        parse_ts("  ")


def test_parse_yyyymmdd_upload_date() -> None:
    ts = parse_ts("20260820")
    assert ts == datetime(2026, 8, 20, tzinfo=timezone.utc)


def test_parse_rfc2822_rss_date() -> None:
    ts = parse_ts("Tue, 25 Aug 2026 22:35:52 +0000")
    assert ts == datetime(2026, 8, 25, 22, 35, 52, tzinfo=timezone.utc)


def test_parse_struct_time() -> None:
    import time

    ts = parse_ts(time.struct_time((2026, 8, 25, 21, 43, 0, 1, 237, 0)))
    assert ts == datetime(2026, 8, 25, 21, 43, 0, tzinfo=timezone.utc)


def test_utcnow_is_timezone_aware() -> None:
    now = utcnow()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)
