from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from btcpoly.db.models import RawPostRow
from btcpoly.db.session import insert_raw_post, session_scope, table_names
from btcpoly.ingestion.schema import RawPost


def test_schema_includes_raw_and_processed_tables(memory_db) -> None:
    names = set(table_names(memory_db))
    expected = {
        "raw_posts",
        "engagement_snapshots",
        "classifications",
        "sentiment",
        "attention_aggregates",
        "events",
        "btc_ticks",
        "polymarket_markets",
        "polymarket_books",
        "features",
        "predictions",
        "paper_trades",
        "live_trades",
        "metrics",
    }
    assert expected.issubset(names)


def test_duplicate_platform_post_id_is_rejected(memory_db) -> None:
    first = RawPost(
        platform="youtube",
        post_id="abc123",
        event_ts="2026-08-24T20:00:00Z",
        text="btc",
    )
    duplicate = RawPost(
        platform="youtube",
        post_id="abc123",
        event_ts="2026-08-24T20:01:00Z",
        text="btc again",
    )
    other = RawPost(
        platform="github",
        post_id="abc123",
        event_ts="2026-08-24T20:00:00Z",
        text="same id different platform",
    )

    with session_scope() as session:
        insert_raw_post(session, first)
        insert_raw_post(session, other)

    with pytest.raises(IntegrityError):
        with session_scope() as session:
            insert_raw_post(session, duplicate)

    with session_scope() as session:
        count = session.query(RawPostRow).count()
        assert count == 2
