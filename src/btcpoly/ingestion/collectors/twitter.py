from __future__ import annotations

import os

from btcpoly.filter.attention import mentions_btc
from btcpoly.ingestion.agent_reach.normalizers import coerce_items, normalize_generic
from btcpoly.ingestion.agent_reach.poller import SkipChannel, require_binary, run_cli
from btcpoly.ingestion.collectors.base import BaseCollector
from btcpoly.ingestion.schema import RawPost
from btcpoly.timeutil import utcnow

# X search is flaky; KOL timelines + home feed are the reliable paths.
# Parallel user-posts calls often return empty under the same cookies — keep sequential.
_TWITTER_TIMEOUT = 40
_MAX_KOLS_PER_POLL = 6
_POSTS_PER_KOL = 3


def twitter_cookies_present() -> bool:
    return bool(os.environ.get("TWITTER_AUTH_TOKEN") and os.environ.get("TWITTER_CT0"))


def _mark_kol(post: RawPost) -> RawPost:
    extra = {**(post.raw_json or {}), "author_influence": True, "keep_reason": "kol"}
    return post.model_copy(update={"raw_json": extra})


def _kol_batch(handles: list[str], *, batch_size: int) -> list[str]:
    """Rotate through the watchlist so each poll covers a different slice."""
    clean = [h.lstrip("@") for h in handles if h and str(h).strip()]
    if not clean:
        return []
    size = min(int(batch_size), len(clean))
    start = int(utcnow().timestamp() // 60) % len(clean)
    return [clean[(start + i) % len(clean)] for i in range(size)]


class TwitterCollector(BaseCollector):
    name = "twitter"

    def collect(self) -> list[RawPost]:
        if not twitter_cookies_present():
            raise SkipChannel("TWITTER_AUTH_TOKEN and TWITTER_CT0 are not set")
        require_binary("twitter")
        timeout = min(_TWITTER_TIMEOUT, self.timeout)
        posts: list[RawPost] = []
        seen: set[str] = set()

        all_kols = [h.lstrip("@") for h in self.settings.kol_twitter if h]
        kols = _kol_batch(all_kols, batch_size=_MAX_KOLS_PER_POLL)
        kol_set = {h.lower() for h in all_kols}

        for handle in kols:
            try:
                payload = run_cli(
                    ["twitter", "user-posts", handle, "-n", str(_POSTS_PER_KOL), "--yaml"],
                    timeout=timeout,
                )
            except (SkipChannel, RuntimeError):
                continue
            for item in coerce_items(payload):
                post = normalize_generic("twitter", item)
                if post.author is None:
                    post = post.model_copy(update={"author": handle})
                # Watchlist accounts: keep everything they post (BTC or not).
                post = _mark_kol(post)
                if post.post_id in seen:
                    continue
                seen.add(post.post_id)
                posts.append(post)

        try:
            feed = run_cli(
                ["twitter", "feed", "-n", str(max(self.limit, 25)), "--yaml"],
                timeout=timeout,
            )
        except (SkipChannel, RuntimeError) as exc:
            if not posts:
                raise SkipChannel(str(exc)) from exc
            feed = []
        for item in coerce_items(feed):
            post = normalize_generic("twitter", item)
            if post.post_id in seen:
                continue
            handle = (post.author or "").lower().lstrip("@")
            if handle in kol_set:
                post = _mark_kol(post)
            elif not mentions_btc(post.text, self.settings, raw_json=post.raw_json):
                continue
            else:
                post = post.model_copy(
                    update={
                        "raw_json": {
                            **(post.raw_json or {}),
                            "keep_reason": "btc_mention",
                        }
                    }
                )
            seen.add(post.post_id)
            posts.append(post)

        if not posts:
            return []

        posts.sort(key=lambda p: p.event_ts or utcnow(), reverse=True)
        kol_posts = [p for p in posts if (p.raw_json or {}).get("author_influence")]
        other = [p for p in posts if not (p.raw_json or {}).get("author_influence")]
        return (kol_posts + other)[: self.limit]
