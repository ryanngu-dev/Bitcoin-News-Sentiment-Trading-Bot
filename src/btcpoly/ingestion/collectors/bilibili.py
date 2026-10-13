from __future__ import annotations

from btcpoly.filter.attention import keep_attention_post
from btcpoly.ingestion.agent_reach.normalizers import coerce_items, normalize_generic
from btcpoly.ingestion.agent_reach.poller import run_cli
from btcpoly.ingestion.collectors.base import BaseCollector
from btcpoly.ingestion.schema import RawPost


class BilibiliCollector(BaseCollector):
    name = "bilibili"

    def collect(self) -> list[RawPost]:
        query = self.settings.attention_queries[0] if self.settings.attention_queries else "比特币"
        # Prefer Chinese Bitcoin query when available — Bilibili corpus is mostly CJK.
        for q in self.settings.attention_queries:
            if "比特" in q:
                query = q
                break
        payload = run_cli(
            ["bili", "search", query, "--type", "video", "-n", str(min(self.limit * 2, 20))],
            timeout=self.timeout,
        )
        posts: list[RawPost] = []
        for item in coerce_items(payload):
            post = normalize_generic("bilibili", item)
            if keep_attention_post(post, self.settings):
                posts.append(post)
            if len(posts) >= self.limit:
                break
        return posts
