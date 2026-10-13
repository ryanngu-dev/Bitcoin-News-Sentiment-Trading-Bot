from __future__ import annotations

from btcpoly.config import Settings
from btcpoly.filter.attention import keep_attention_post, mentions_btc
from btcpoly.ingestion.schema import RawPost

__all__ = ["BaseCollector", "keep_attention_post", "mentions_btc"]


class BaseCollector:
    name = "base"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def limit(self) -> int:
        return max(1, self.settings.ingest.limit)

    @property
    def timeout(self) -> int:
        return max(5, self.settings.ingest.timeout_seconds)

    def collect(self) -> list[RawPost]:
        raise NotImplementedError
