from __future__ import annotations

from btcpoly.config import Settings
from btcpoly.ingestion.collectors.bilibili import BilibiliCollector
from btcpoly.ingestion.collectors.github import GithubCollector
from btcpoly.ingestion.collectors.reddit import RedditCollector
from btcpoly.ingestion.collectors.rss import RssCollector
from btcpoly.ingestion.collectors.twitter import TwitterCollector
from btcpoly.ingestion.collectors.v2ex import V2exCollector
from btcpoly.ingestion.collectors.web import WebCollector
from btcpoly.ingestion.collectors.xhs import XiaohongshuCollector
from btcpoly.ingestion.collectors.youtube import YoutubeCollector

COLLECTOR_TYPES = {
    "rss": RssCollector,
    "web": WebCollector,
    "youtube": YoutubeCollector,
    "github": GithubCollector,
    "bilibili": BilibiliCollector,
    "v2ex": V2exCollector,
    "twitter": TwitterCollector,
    "reddit": RedditCollector,
    "xiaohongshu": XiaohongshuCollector,
}


def build_collectors(settings: Settings, channels: list[str] | None = None) -> list:
    wanted = channels or list(settings.agent_reach.channels)
    collectors = []
    for name in wanted:
        cls = COLLECTOR_TYPES.get(name)
        if cls is None:
            continue
        collectors.append(cls(settings))
    return collectors
