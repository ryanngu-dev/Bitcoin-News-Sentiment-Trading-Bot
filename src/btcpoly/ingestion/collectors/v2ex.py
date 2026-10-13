from __future__ import annotations

import json

from btcpoly.filter.attention import keep_attention_post
from btcpoly.ingestion.agent_reach.normalizers import coerce_items, normalize_v2ex
from btcpoly.ingestion.agent_reach.poller import SkipChannel
from btcpoly.ingestion.collectors.base import BaseCollector
from btcpoly.ingestion.collectors.http import fetch_text
from btcpoly.ingestion.schema import RawPost


class V2exCollector(BaseCollector):
    name = "v2ex"

    def collect(self) -> list[RawPost]:
        try:
            raw = fetch_text(
                "https://www.v2ex.com/api/topics/hot.json",
                timeout=min(8, self.timeout),
                attempts=1,
            )
        except Exception as exc:
            raise SkipChannel("v2ex timed out") from exc
        payload = json.loads(raw)
        posts: list[RawPost] = []
        for item in coerce_items(payload):
            post = normalize_v2ex(item)
            if keep_attention_post(post, self.settings):
                posts.append(post)
            if len(posts) >= self.limit:
                break
        return posts
