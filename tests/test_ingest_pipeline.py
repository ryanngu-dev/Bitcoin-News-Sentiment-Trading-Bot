from __future__ import annotations

from pathlib import Path

from btcpoly.db.models import RawPostRow
from btcpoly.db.session import insert_raw_post_or_skip, session_scope
from btcpoly.ingestion.agent_reach.poller import SkipChannel
from btcpoly.ingestion.collectors.twitter import TwitterCollector
from btcpoly.ingestion.collectors.youtube import YoutubeCollector
from btcpoly.ingestion.pipeline import run_ingest
from btcpoly.ingestion.schema import RawPost
from btcpoly.timeutil import utcnow


class _FakeCollector:
    name = "rss"

    def __init__(self, posts: list[RawPost]) -> None:
        self._posts = posts

    def collect(self) -> list[RawPost]:
        return list(self._posts)


def test_insert_or_skip_dedupes(memory_db, settings) -> None:
    post = RawPost(
        platform="rss",
        post_id="same",
        event_ts="2026-08-24T20:00:00Z",
        text="btc",
    )
    with session_scope() as session:
        assert insert_raw_post_or_skip(session, post) is True
        assert insert_raw_post_or_skip(session, post) is False
        assert session.query(RawPostRow).count() == 1


def test_pipeline_counts_duplicates(memory_db, settings, monkeypatch) -> None:
    from btcpoly.timeutil import utcnow

    post = RawPost(
        platform="rss",
        post_id="dup-1",
        event_ts=utcnow().isoformat(),
        text="btc",
    )
    monkeypatch.setattr(
        "btcpoly.ingestion.pipeline.build_collectors",
        lambda _settings, channels=None: [_FakeCollector([post])],
    )
    first = run_ingest(settings, channels=["rss"])
    second = run_ingest(settings, channels=["rss"])
    assert first.inserted == 1
    assert second.inserted == 0
    assert second.duplicates == 1
    assert second.exit_code() == 0


def test_rss_skips_failed_feed(settings, monkeypatch) -> None:
    from btcpoly.ingestion.collectors.rss import RssCollector

    def fail(*_a, **_k):
        raise RuntimeError("timeout")

    monkeypatch.setattr("btcpoly.ingestion.collectors.rss.fetch_bytes", fail)
    posts = RssCollector(settings).collect()
    assert posts == []


def test_require_binary_finds_venv_neighbor(tmp_path, monkeypatch) -> None:
    import sys

    from btcpoly.ingestion.agent_reach.poller import require_binary

    fake_py = tmp_path / "python.exe"
    fake_py.write_text("", encoding="utf-8")
    tool = tmp_path / "yt-dlp.exe"
    tool.write_text("", encoding="utf-8")
    monkeypatch.setattr("btcpoly.ingestion.agent_reach.poller.shutil.which", lambda _name: None)
    monkeypatch.setattr(sys, "executable", str(fake_py))
    assert Path(require_binary("yt-dlp")) == tool


def test_missing_ytdlp_skips(settings, monkeypatch) -> None:
    monkeypatch.setattr("btcpoly.ingestion.agent_reach.poller.shutil.which", lambda _name: None)
    monkeypatch.setattr("btcpoly.ingestion.agent_reach.poller.extra_binary_candidates", lambda _name: [])
    collector = YoutubeCollector(settings)
    try:
        collector.collect()
        raise AssertionError("expected SkipChannel")
    except SkipChannel as exc:
        assert "yt-dlp" in exc.reason


def test_youtube_drops_day_only_upload_dates(settings, monkeypatch) -> None:
    """Flat search alone has no unix timestamp — enrich path must supply it or drop."""

    def fake_run(command, *, timeout, env=None, attempts=1):
        joined = " ".join(str(part) for part in command)
        if "youtube.com/results" in joined:
            return [
                {
                    "id": "old",
                    "title": "Bitcoin breakout",
                    "uploader": "Davinci Jeremie",
                    "upload_date": "20260820",
                },
                {
                    "id": "new",
                    "title": "Bitcoin today",
                    "uploader": "FreshChannel",
                    "upload_date": utcnow().strftime("%Y%m%d"),
                },
            ]
        # Enrich dumps without timestamp still fail freshness.
        return {
            "id": "new",
            "title": "Bitcoin today",
            "uploader": "FreshChannel",
            "upload_date": utcnow().strftime("%Y%m%d"),
        }

    monkeypatch.setattr("btcpoly.ingestion.collectors.youtube.run_cli", fake_run)
    posts = YoutubeCollector(settings).collect()
    assert posts == []


def test_youtube_keeps_posts_with_real_timestamps(settings, monkeypatch) -> None:
    now = utcnow()

    def fake_run(command, *, timeout, env=None, attempts=1):
        joined = " ".join(str(part) for part in command)
        if "youtube.com/results" in joined:
            return [
                {
                    "id": "fresh",
                    "title": "Bitcoin live",
                    "uploader": "FreshChannel",
                },
            ]
        assert "watch?v=fresh" in joined
        return {
            "id": "fresh",
            "title": "Bitcoin live",
            "uploader": "FreshChannel",
            "upload_date": now.strftime("%Y%m%d"),
            "timestamp": int(now.timestamp()),
            "webpage_url": "https://www.youtube.com/watch?v=fresh",
        }

    monkeypatch.setattr("btcpoly.ingestion.collectors.youtube.run_cli", fake_run)
    posts = YoutubeCollector(settings).collect()
    assert [p.post_id for p in posts] == ["fresh"]
    assert abs((posts[0].event_ts - now).total_seconds()) < 2


def test_twitter_skips_without_cookies(settings, monkeypatch) -> None:
    monkeypatch.delenv("TWITTER_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TWITTER_CT0", raising=False)
    collector = TwitterCollector(settings)
    try:
        collector.collect()
        raise AssertionError("expected SkipChannel")
    except SkipChannel as exc:
        assert "TWITTER" in exc.reason


def test_twitter_uses_user_posts_and_feed(settings, monkeypatch) -> None:
    monkeypatch.setenv("TWITTER_AUTH_TOKEN", "tok")
    monkeypatch.setenv("TWITTER_CT0", "ct0")
    calls: list[list[str]] = []

    def fake_require(name: str) -> str:
        return name

    def fake_run(command, *, timeout, env=None, attempts=1):
        calls.append(command)
        if command[1] == "user-posts":
            return {
                "ok": True,
                "data": [
                    {
                        "id": f"100-{command[2]}",
                        "text": "Just had coffee",  # KOL noise kept on purpose
                        "author": {"screenName": command[2]},
                        "createdAtISO": "2026-08-25T19:00:00+00:00",
                    }
                ],
            }
        if command[1] == "feed":
            return {
                "ok": True,
                "data": [
                    {
                        "id": "200",
                        "text": "BTC ripping",
                        "author": {"screenName": "rando"},
                        "createdAtISO": "2026-08-25T19:05:00+00:00",
                    },
                    {
                        "id": "201",
                        "text": "cats are cute",
                        "author": {"screenName": "meow"},
                        "createdAtISO": "2026-08-25T19:06:00+00:00",
                    },
                ],
            }
        raise AssertionError(f"unexpected command {command}")

    monkeypatch.setattr("btcpoly.ingestion.collectors.twitter.require_binary", fake_require)
    monkeypatch.setattr("btcpoly.ingestion.collectors.twitter.run_cli", fake_run)
    posts = TwitterCollector(settings).collect()
    assert any(c[1] == "user-posts" for c in calls)
    assert any(c[1] == "feed" for c in calls)
    assert not any(c[1] == "search" for c in calls)
    assert any(p.raw_json.get("author_influence") for p in posts)
    assert any(p.post_id.startswith("100-") for p in posts)  # non-BTC KOL kept
    assert any(p.post_id == "200" for p in posts)
    assert all(p.post_id != "201" for p in posts)


def test_keep_kol_without_btc_mention(settings) -> None:
    from btcpoly.filter.attention import keep_attention_post
    from btcpoly.ingestion.schema import RawPost
    from btcpoly.timeutil import utcnow

    kol = RawPost(
        platform="twitter",
        post_id="kol1",
        event_ts=utcnow(),
        text="Shipping a new product tomorrow",
        author="saylor",
        raw_json={"author_influence": True},
    )
    rando = RawPost(
        platform="twitter",
        post_id="r1",
        event_ts=utcnow(),
        text="Shipping a new product tomorrow",
        author="rando",
        raw_json={},
    )
    assert keep_attention_post(kol, settings) is True
    assert keep_attention_post(rando, settings) is False


def test_run_cli_missing_file_skips_without_retry(monkeypatch) -> None:
    from btcpoly.ingestion.agent_reach.poller import run_cli

    monkeypatch.setattr(
        "btcpoly.ingestion.agent_reach.poller.shutil.which",
        lambda _name: r"C:\fake\opencli.exe",
    )
    calls = {"n": 0}

    def boom(*_a, **_k):
        calls["n"] += 1
        raise FileNotFoundError("missing")

    monkeypatch.setattr("btcpoly.ingestion.agent_reach.poller.subprocess.run", boom)
    try:
        run_cli(["opencli", "reddit", "search", "btc"], timeout=5)
        raise AssertionError("expected SkipChannel")
    except SkipChannel as exc:
        assert "opencli" in exc.reason
    assert calls["n"] == 1


def test_run_cli_timeout_skips_without_retry(monkeypatch) -> None:
    import subprocess

    from btcpoly.ingestion.agent_reach.poller import run_cli

    monkeypatch.setattr(
        "btcpoly.ingestion.agent_reach.poller.shutil.which",
        lambda _name: r"C:\fake\opencli.exe",
    )
    calls = {"n": 0}

    def fake_run(*_a, **_k):
        calls["n"] += 1
        raise subprocess.TimeoutExpired(cmd="opencli", timeout=6)

    monkeypatch.setattr("btcpoly.ingestion.agent_reach.poller.subprocess.run", fake_run)
    try:
        run_cli(["opencli", "reddit", "search", "btc"], timeout=6)
        raise AssertionError("expected SkipChannel")
    except SkipChannel as exc:
        assert "timed out" in exc.reason
    assert calls["n"] == 1


def test_run_cli_browser_connect_skips_once(monkeypatch) -> None:
    from btcpoly.ingestion.agent_reach.poller import run_cli

    monkeypatch.setattr(
        "btcpoly.ingestion.agent_reach.poller.shutil.which",
        lambda _name: r"C:\fake\opencli.exe",
    )
    calls = {"n": 0}

    def fake_run(*_a, **_k):
        calls["n"] += 1
        return type(
            "Result",
            (),
            {
                "returncode": 69,
                "stdout": "",
                "stderr": "BROWSER_CONNECT\nBrowser Bridge extension not connected",
            },
        )()

    monkeypatch.setattr("btcpoly.ingestion.agent_reach.poller.subprocess.run", fake_run)
    try:
        run_cli(["opencli", "reddit", "search", "btc"], timeout=60)
        raise AssertionError("expected SkipChannel")
    except SkipChannel as exc:
        assert "BROWSER_CONNECT" in exc.reason
    assert calls["n"] == 1


def test_sticky_skip_does_not_recall_collector(memory_db, settings, monkeypatch) -> None:
    calls = {"n": 0}

    class _Skipper:
        name = "reddit"

        def collect(self):
            calls["n"] += 1
            raise SkipChannel("BROWSER_CONNECT: Browser Bridge extension not connected")

    monkeypatch.setattr(
        "btcpoly.ingestion.pipeline.build_collectors",
        lambda _settings, channels=None: [_Skipper()],
    )
    first = run_ingest(settings, channels=["reddit"])
    second = run_ingest(settings, channels=["reddit"])
    assert first.channels[0].skipped
    assert second.channels[0].skipped
    assert calls["n"] == 1
    assert second.exit_code() == 0


def test_reddit_skips_when_clis_missing(settings, monkeypatch) -> None:
    from btcpoly.ingestion.collectors.reddit import RedditCollector

    monkeypatch.setattr("btcpoly.ingestion.agent_reach.poller.shutil.which", lambda _name: None)
    monkeypatch.setattr("btcpoly.ingestion.agent_reach.poller.extra_binary_candidates", lambda _name: [])
    collector = RedditCollector(settings)
    try:
        collector.collect()
        raise AssertionError("expected SkipChannel")
    except SkipChannel as exc:
        assert "PATH" in exc.reason


def test_reddit_prefers_new_day_search(settings, monkeypatch) -> None:
    from btcpoly.ingestion.collectors.reddit import RedditCollector
    from btcpoly.timeutil import utcnow

    calls: list[list[str]] = []

    def fake_require(name: str) -> str:
        if name != "opencli":
            raise SkipChannel(f"{name} not on PATH")
        return name

    def fake_run(command, *, timeout, env=None, attempts=1):
        calls.append(command)
        now = int(utcnow().timestamp())
        return [
            {
                "id": "new1",
                "title": "Bitcoin pumps today",
                "author": "alice",
                "created_utc": now,
                "subreddit": "bitcoin",
            },
            {
                "id": "old1",
                "title": "Bitcoin from 2017",
                "author": "bob",
                "created_utc": now - 86400 * 400,
                "subreddit": "bitcoin",
            },
        ]

    monkeypatch.setattr("btcpoly.ingestion.collectors.reddit.require_binary", fake_require)
    monkeypatch.setattr("btcpoly.ingestion.collectors.reddit.run_cli", fake_run)
    posts = RedditCollector(settings).collect()
    assert len(calls) == 1
    search = calls[0]
    assert "--sort" in search and "new" in search
    assert "--time" in search and "hour" in search
    assert all(p.post_id != "old1" for p in posts)
    assert any(p.post_id == "new1" for p in posts)

def test_live_channel_loops_run_channels_concurrently(memory_db, settings, monkeypatch) -> None:
    import threading
    import time
    from btcpoly.ingestion.pipeline import run_live_channel_loops

    active: set[str] = set()
    lock = threading.Lock()
    overlap = {"seen": False}
    polls = {"rss": 0, "github": 0}

    class _Slow:
        def __init__(self, name: str, delay: float) -> None:
            self.name = name
            self.delay = delay

        def collect(self):
            with lock:
                active.add(self.name)
                if len(active) >= 2:
                    overlap["seen"] = True
            time.sleep(self.delay)
            with lock:
                active.discard(self.name)
                polls[self.name] = polls.get(self.name, 0) + 1
            return []

    monkeypatch.setattr(
        "btcpoly.ingestion.pipeline.build_collectors",
        lambda _settings, channels=None: [_Slow("rss", 0.15), _Slow("github", 0.15)],
    )
    stop_after = time.time() + 0.45
    run_live_channel_loops(
        settings,
        channels=["rss", "github"],
        interval_seconds=0,
        should_stop=lambda: time.time() >= stop_after,
        sleep_fn=time.sleep,
    )
    assert overlap["seen"] is True
    assert polls["rss"] >= 1
    assert polls["github"] >= 1
