from __future__ import annotations

from btcpoly.filter.attention import keep_attention_post
from btcpoly.ingestion.agent_reach.normalizers import coerce_items, normalize_generic
from btcpoly.ingestion.agent_reach.poller import SkipChannel, require_binary, run_cli
from btcpoly.ingestion.collectors.base import BaseCollector
from btcpoly.ingestion.schema import RawPost

# OpenCLI drives a real Chrome tab — one call only, keep it tight.
_OPENCLI_TIMEOUT = 20


class RedditCollector(BaseCollector):
    name = "reddit"

    def collect(self) -> list[RawPost]:
        query = " ".join(self.settings.attention_queries[:2]) or "bitcoin"
        timeout = min(_OPENCLI_TIMEOUT, self.timeout)
        try:
            require_binary("opencli")
            payload = run_cli(
                [
                    "opencli",
                    "reddit",
                    "search",
                    query,
                    "--sort",
                    "new",
                        "--time",
                        "hour",
                        "--limit",
                    str(min(self.limit, 15)),
                    "-f",
                    "yaml",
                ],
                timeout=timeout,
            )
        except SkipChannel:
            require_binary("rdt")
            payload = run_cli(
                ["rdt", "search", query, "--limit", str(self.limit)],
                timeout=timeout,
            )

        posts: list[RawPost] = []
        for item in coerce_items(payload):
            post = normalize_generic("reddit", item)
            if keep_attention_post(post, self.settings):
                posts.append(post)
            if len(posts) >= self.limit:
                break
        posts.sort(key=lambda item: item.event_ts, reverse=True)
        return posts[: self.limit]
