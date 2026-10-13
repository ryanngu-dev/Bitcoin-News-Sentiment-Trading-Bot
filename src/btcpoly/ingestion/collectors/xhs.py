from __future__ import annotations

from btcpoly.ingestion.agent_reach.normalizers import coerce_items, normalize_generic
from btcpoly.ingestion.agent_reach.poller import run_cli
from btcpoly.ingestion.collectors.base import BaseCollector
from btcpoly.ingestion.schema import RawPost

_OPENCLI_TIMEOUT = 6


class XiaohongshuCollector(BaseCollector):
    name = "xiaohongshu"

    def collect(self) -> list[RawPost]:
        query = self.settings.attention_queries[0] if self.settings.attention_queries else "比特币"
        payload = run_cli(
            ["opencli", "xiaohongshu", "search", query, "-f", "yaml"],
            timeout=min(_OPENCLI_TIMEOUT, self.timeout),
        )
        return [
            normalize_generic("xiaohongshu", item)
            for item in coerce_items(payload)[: self.limit]
        ]
