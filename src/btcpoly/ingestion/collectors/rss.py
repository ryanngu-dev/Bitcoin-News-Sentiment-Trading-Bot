from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

import feedparser

from btcpoly.filter.attention import keep_attention_post
from btcpoly.ingestion.agent_reach.normalizers import normalize_rss_entry
from btcpoly.ingestion.collectors.base import BaseCollector
from btcpoly.ingestion.collectors.http import fetch_bytes
from btcpoly.ingestion.schema import RawPost

_SCAN_PER_FEED = 30
_FEED_TIMEOUT = 8
_MAX_WORKERS = 12


class RssCollector(BaseCollector):
    name = "rss"

    def _fetch_feed(self, url: str) -> list[RawPost]:
        timeout = min(_FEED_TIMEOUT, self.timeout)
        try:
            raw = fetch_bytes(url, timeout=timeout, attempts=1)
        except (RuntimeError, TimeoutError, OSError):
            return []
        parsed = feedparser.parse(raw)
        entries = list(getattr(parsed, "entries", []) or [])
        posts: list[RawPost] = []
        for entry in entries[:_SCAN_PER_FEED]:
            post = normalize_rss_entry(dict(entry), url)
            if post is None:
                continue
            # Credibility is AI-scored later; do not hard-drop low-tier hosts here.
            if keep_attention_post(post, self.settings):
                posts.append(post)
        return posts

    def collect(self) -> list[RawPost]:
        feeds = list(self.settings.ingest.rss_feeds)
        if not feeds:
            return []
        posts: list[RawPost] = []
        seen: set[str] = set()
        workers = min(_MAX_WORKERS, len(feeds))
        pool = ThreadPoolExecutor(max_workers=workers)
        futures = []
        try:
            futures = [pool.submit(self._fetch_feed, url) for url in feeds]
            for future in as_completed(futures):
                for post in future.result():
                    key = post.url or post.post_id
                    if key in seen:
                        continue
                    seen.add(key)
                    posts.append(post)
        except KeyboardInterrupt:
            for future in futures:
                future.cancel()
            raise
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        posts.sort(key=lambda item: item.event_ts, reverse=True)
        return posts[: self.limit]
