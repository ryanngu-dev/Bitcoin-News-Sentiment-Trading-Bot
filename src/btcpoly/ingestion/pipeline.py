from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from btcpoly.config import Settings
from btcpoly.db.models import Metric
from btcpoly.db.session import insert_raw_post_or_skip, session_scope
from btcpoly.filter.attention import keep_attention_post, localize_post
from btcpoly.ingestion.agent_reach.poller import SkipChannel
from btcpoly.ingestion.collectors import build_collectors
from btcpoly.ingestion.schema import RawPost
from btcpoly.logging import get_logger
from btcpoly.attention.ai_score import score_recent_posts_ai
from btcpoly.monitoring.feed import SourceHeadline, headline_from_post, sort_headlines
from btcpoly.timeutil import utcnow

log = get_logger(__name__)

_sticky_skips: dict[str, str] = {}
_sticky_lock = threading.Lock()


def clear_channel_skips() -> None:
    with _sticky_lock:
        _sticky_skips.clear()


def _sticky_reason(channel: str, reason: str) -> bool:
    text = reason.lower()
    if any(
        marker in text
        for marker in (
            "browser_connect",
            "browser bridge",
            "not on path",
            "twitter_auth_token and twitter_ct0 are not set",
            "no twitter cookies found",
            "not_authenticated",
            "clienttransaction",
            "twitter_cli.client",
            "auth_required",
            "login wall",
            "unsupported url scheme",
            "rate limit",
            "http 403",
            "api rate limit",
        )
    ):
        return True
    # Empty polls / flaky X timeouts must NOT sticky — Twitter should retry every cycle.
    if channel in {"reddit", "xiaohongshu", "v2ex", "youtube"} and (
        "timeout" in text or "timed out" in text
    ):
        return True
    return False


@dataclass
class ChannelReport:
    channel: str
    fetched: int = 0
    inserted: int = 0
    duplicates: int = 0
    skipped: str | None = None
    error: str | None = None


@dataclass
class IngestSummary:
    fetched: int = 0
    inserted: int = 0
    duplicates: int = 0
    dry_run: bool = False
    ingested_at: datetime = field(default_factory=utcnow)
    channels: list[ChannelReport] = field(default_factory=list)
    sources: list[SourceHeadline] = field(default_factory=list)

    @property
    def errors(self) -> list[dict[str, str]]:
        return [
            {"channel": row.channel, "error": row.error}
            for row in self.channels
            if row.error
        ]

    def exit_code(self) -> int:
        if any(row.error for row in self.channels):
            return 2
        return 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "fetched": self.fetched,
            "inserted": self.inserted,
            "duplicates": self.duplicates,
            "dry_run": self.dry_run,
            "ingested_at": self.ingested_at.isoformat(),
            "errors": self.errors,
            "skipped": [
                {"channel": row.channel, "reason": row.skipped}
                for row in self.channels
                if row.skipped
            ],
            "channels": [asdict(row) for row in self.channels],
            "sources": [item.to_dict() for item in self.sources],
        }


def _collect_one(collector) -> tuple[str, list[RawPost] | None, str | None, str | None]:
    """Return (name, posts|None, skip_reason|None, error|None)."""
    try:
        return collector.name, collector.collect(), None, None
    except SkipChannel as exc:
        return collector.name, None, exc.reason, None
    except Exception as exc:  # channel stays isolated
        return collector.name, None, None, str(exc)[:500]


def run_ingest(
    settings: Settings,
    *,
    dry_run: bool = False,
    channels: list[str] | None = None,
    on_channel: Callable[[str], None] | None = None,
) -> IngestSummary:
    summary = IngestSummary(dry_run=dry_run, ingested_at=utcnow())
    collectors = build_collectors(settings, channels)
    if dry_run:
        for collector in collectors:
            summary.channels.append(ChannelReport(channel=collector.name, skipped="dry-run"))
        return summary

    active = []
    for collector in collectors:
        with _sticky_lock:
            cached = _sticky_skips.get(collector.name)
        if cached:
            summary.channels.append(ChannelReport(channel=collector.name, skipped=cached))
            continue
        active.append(collector)

    results: dict[str, tuple[list[RawPost] | None, str | None, str | None]] = {}
    if active:
        if on_channel is not None:
            on_channel(", ".join(c.name for c in active))
        workers = max(1, len(active))
        pool = ThreadPoolExecutor(max_workers=workers)
        futures: dict = {}
        try:
            futures = {pool.submit(_collect_one, collector): collector.name for collector in active}
            for future in as_completed(futures):
                name, posts, skipped, error = future.result()
                results[name] = (posts, skipped, error)
                if on_channel is not None:
                    on_channel(f"done:{name}")
        except KeyboardInterrupt:
            for future in futures:
                future.cancel()
            raise
        finally:
            # wait=False avoids the noisy "Exception ignored on threading shutdown"
            # traceback when the user hits Ctrl+C mid-poll.
            pool.shutdown(wait=False, cancel_futures=True)

    # Persist in configured channel order so reports stay stable.
    for collector in collectors:
        if collector.name not in results:
            continue
        posts, skipped, error = results[collector.name]
        report = ChannelReport(channel=collector.name)
        if skipped:
            report.skipped = skipped
            if _sticky_reason(collector.name, skipped):
                with _sticky_lock:
                    _sticky_skips[collector.name] = skipped
            log.debug("skip %s: %s", collector.name, skipped)
            summary.channels.append(report)
            continue
        if error:
            if _sticky_reason(collector.name, error):
                report.skipped = error
                with _sticky_lock:
                    _sticky_skips[collector.name] = error
                summary.channels.append(report)
                continue
            report.error = error
            log.error("channel %s failed: %s", collector.name, error)
            summary.channels.append(report)
            continue

        assert posts is not None
        posts = [
            localize_post(post)
            for post in posts
            if keep_attention_post(post, settings)
        ]
        report.fetched = len(posts)
        summary.fetched += report.fetched
        with session_scope() as session:
            for post in posts:
                post.ingested_at = utcnow()
                inserted = insert_raw_post_or_skip(session, post)
                if inserted:
                    report.inserted += 1
                else:
                    report.duplicates += 1
                summary.sources.append(
                    headline_from_post(
                        post.platform,
                        post.text,
                        post.author,
                        post.url,
                        {**(post.raw_json or {}), "id": (post.raw_json or {}).get("id") or post.post_id},
                        event_ts=post.event_ts,
                    )
                )
        summary.inserted += report.inserted
        summary.duplicates += report.duplicates
        summary.channels.append(report)

    summary.sources = sort_headlines(summary.sources, newest_first=False)[:25]

    summary_extra = summary.to_dict()
    # Warm AI lean cache for recent posts (no-op without API key).
    try:
        with session_scope() as session:
            summary_extra["ai_sentiment"] = score_recent_posts_ai(session, settings)
    except Exception as exc:  # noqa: BLE001
        log.warning("ai sentiment after ingest failed: %s", exc)
        summary_extra["ai_sentiment"] = {"enabled": False, "error": str(exc)[:200]}

    with session_scope() as session:
        session.add(
            Metric(
                name="ingest_run",
                value=float(summary.inserted),
                extra=summary_extra,
            )
        )
    return summary


# Minimum seconds between polls per channel in the live multi-thread loop.
# GitHub search is aggressively rate-limited; don't spin it every second.
_CHANNEL_MIN_INTERVAL_SECONDS: dict[str, int] = {
    "github": 600,
    "twitter": 15,
    "rss": 10,
    "reddit": 30,
    "youtube": 60,
    "v2ex": 45,
    "bilibili": 60,
    "web": 60,
    "xiaohongshu": 60,
}


def run_live_channel_loops(
    settings: Settings,
    *,
    channels: list[str] | None = None,
    interval_seconds: int = 0,
    on_summary: Callable[[IngestSummary], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> None:
    """Run every channel on its own thread so scrapers stay concurrent.

    Slow Twitter does not block RSS/YouTube/etc. — each platform re-polls
    as soon as it finishes its own cycle (subject to per-channel min interval).
    """
    collectors = build_collectors(settings, channels)
    if not collectors:
        return
    stop = threading.Event()
    base_wait = max(0, int(interval_seconds))

    def _worker(name: str) -> None:
        channel_wait = max(base_wait, int(_CHANNEL_MIN_INTERVAL_SECONDS.get(name, 15)))
        while not stop.is_set():
            if should_stop is not None and should_stop():
                stop.set()
                break
            try:
                summary = run_ingest(settings, channels=[name])
            except Exception as exc:  # noqa: BLE001 — keep sibling channels alive
                log.error("live channel %s crashed: %s", name, exc)
                summary = IngestSummary()
                summary.channels.append(
                    ChannelReport(channel=name, error=str(exc)[:500])
                )
            if on_summary is not None:
                try:
                    on_summary(summary)
                except Exception:  # noqa: BLE001
                    log.exception("on_summary failed for %s", name)
            if stop.is_set():
                break
            # After a rate-limit sticky skip, back off hard so we don't log-spam.
            skipped = " ".join(
                str(row.skipped or row.error or "") for row in summary.channels
            ).lower()
            wait = channel_wait
            if "rate limit" in skipped or "http 403" in skipped:
                wait = max(wait, 900)
            sleep_fn(wait)

    threads = [
        threading.Thread(
            target=_worker,
            name=f"ingest-{collector.name}",
            args=(collector.name,),
            daemon=True,
        )
        for collector in collectors
    ]
    for thread in threads:
        thread.start()
    try:
        while any(thread.is_alive() for thread in threads):
            if should_stop is not None and should_stop():
                stop.set()
                break
            sleep_fn(0.25)
    except KeyboardInterrupt:
        stop.set()
        raise
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=1.0)
