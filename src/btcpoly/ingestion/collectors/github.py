from __future__ import annotations

from btcpoly.filter.attention import keep_attention_post
from btcpoly.ingestion.agent_reach.normalizers import coerce_items, normalize_github
from btcpoly.ingestion.agent_reach.poller import SkipChannel, require_binary, run_cli
from btcpoly.ingestion.collectors.base import BaseCollector
from btcpoly.ingestion.schema import RawPost


class GithubCollector(BaseCollector):
    name = "github"

    def collect(self) -> list[RawPost]:
        require_binary("gh")
        query = " ".join(self.settings.attention_queries[:2]) or "bitcoin"
        try:
            payload = run_cli(
                [
                    "gh",
                    "search",
                    "repos",
                    query,
                    "--sort",
                    "updated",
                    "--limit",
                    str(min(self.limit * 2, 20)),
                    "--json",
                    "fullName,url,description,updatedAt,owner",
                ],
                timeout=self.timeout,
            )
        except SkipChannel:
            raise
        except RuntimeError as exc:
            text = str(exc).lower()
            if "rate limit" in text or "http 403" in text or "403" in text:
                raise SkipChannel(f"github rate limited: {exc}") from exc
            raise
        posts: list[RawPost] = []
        for item in coerce_items(payload):
            post = normalize_github(item)
            if keep_attention_post(post, self.settings):
                posts.append(post)
            if len(posts) >= self.limit:
                break
        return posts
