from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus

from btcpoly.filter.attention import keep_attention_post, mentions_btc
from btcpoly.ingestion.agent_reach.normalizers import coerce_items, normalize_youtube
from btcpoly.ingestion.agent_reach.poller import run_cli
from btcpoly.ingestion.collectors.base import BaseCollector
from btcpoly.ingestion.schema import RawPost

# Flat search has no real clock time — enrich a shortlist with full metadata.
_SEARCH_SCAN = 24
_ENRICH_CANDIDATES = 8
_ENRICH_WORKERS = 4
_SEARCH_TIMEOUT = 45
_ENRICH_TIMEOUT = 25


class YoutubeCollector(BaseCollector):
    name = "youtube"

    def _flat_search(self, query: str) -> list[dict]:
        # Real YouTube results URL sorted by upload date (CAI%3D).
        # Avoid ytsearchdateN:query — on Windows that is parsed as a drive/URL scheme.
        search_url = (
            "https://www.youtube.com/results?"
            f"search_query={quote_plus(query)}&sp=CAI%253D"
        )
        payload = run_cli(
            [
                "yt-dlp",
                search_url,
                "--dump-json",
                "--flat-playlist",
                "--playlist-end",
                str(max(_SEARCH_SCAN, self.limit * 3)),
                "--no-download",
                "--ignore-errors",
            ],
            timeout=min(_SEARCH_TIMEOUT, self.timeout),
        )
        return [item for item in coerce_items(payload) if isinstance(item, dict)]

    def _enrich_one(self, video_id: str) -> dict | None:
        try:
            payload = run_cli(
                [
                    "yt-dlp",
                    f"https://www.youtube.com/watch?v={video_id}",
                    "--dump-json",
                    "--no-download",
                    "--ignore-errors",
                    "--skip-download",
                ],
                timeout=min(_ENRICH_TIMEOUT, self.timeout),
            )
        except Exception:
            return None
        items = coerce_items(payload)
        for item in items:
            if isinstance(item, dict) and (item.get("id") == video_id or item.get("timestamp")):
                return item
        return items[0] if items and isinstance(items[0], dict) else None

    def collect(self) -> list[RawPost]:
        query = self.settings.attention_queries[0] if self.settings.attention_queries else "Bitcoin"
        flat_items = self._flat_search(query)

        # Prefer titles that actually mention BTC before paying for full metadata.
        candidates: list[dict] = []
        seen: set[str] = set()
        for item in flat_items:
            vid = str(item.get("id") or "").strip()
            if not vid or vid in seen:
                continue
            title = str(item.get("title") or "")
            if not mentions_btc(title, self.settings, raw_json=item):
                continue
            seen.add(vid)
            candidates.append(item)
            if len(candidates) >= _ENRICH_CANDIDATES:
                break

        enriched: list[dict] = []
        if candidates:
            pool = ThreadPoolExecutor(max_workers=min(_ENRICH_WORKERS, len(candidates)))
            futures: dict = {}
            try:
                futures = {
                    pool.submit(self._enrich_one, str(item["id"])): item for item in candidates
                }
                for future in as_completed(futures):
                    full = future.result()
                    base = futures[future]
                    if full is None:
                        continue
                    # Keep flat title/uploader if full dump omits them.
                    merged = {**base, **full}
                    if not merged.get("timestamp") and not merged.get("release_timestamp"):
                        continue
                    enriched.append(merged)
            except KeyboardInterrupt:
                for future in futures:
                    future.cancel()
                raise
            finally:
                pool.shutdown(wait=False, cancel_futures=True)

        posts: list[RawPost] = []
        for item in enriched:
            post = normalize_youtube(item)
            if keep_attention_post(post, self.settings):
                posts.append(post)
        posts.sort(key=lambda item: item.event_ts, reverse=True)
        return posts[: self.limit]
