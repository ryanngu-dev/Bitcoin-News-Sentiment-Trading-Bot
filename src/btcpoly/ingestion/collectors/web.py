from __future__ import annotations

from btcpoly.filter.attention import keep_attention_post
from btcpoly.ingestion.agent_reach.normalizers import normalize_web_page
from btcpoly.ingestion.collectors.base import BaseCollector
from btcpoly.ingestion.collectors.http import fetch_text
from btcpoly.ingestion.schema import RawPost


class WebCollector(BaseCollector):
    name = "web"

    def collect(self) -> list[RawPost]:
        posts: list[RawPost] = []
        for url in self.settings.ingest.news_urls[: self.limit]:
            target = url if url.startswith("http") else f"https://{url}"
            jina = f"https://r.jina.ai/{target}"
            markdown = fetch_text(jina, timeout=self.timeout)
            post = normalize_web_page(target, markdown)
            if keep_attention_post(post, self.settings):
                posts.append(post)
        return posts
