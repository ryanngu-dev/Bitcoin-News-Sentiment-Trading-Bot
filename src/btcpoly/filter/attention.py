"""Keep posts that actually mention BTC, then translate CJK headlines to English."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from btcpoly.config import Settings
from btcpoly.ingestion.schema import RawPost
from btcpoly.text.translate import has_cjk, translate_to_english
from btcpoly.timeutil import to_utc, utcnow

_CJK_QUERY = re.compile(r"[\u3400-\u9fff]")

# Per-platform freshness for a trading bot (minutes). Social should be fresher than RSS.
_PLATFORM_MAX_AGE_MINUTES = {
    # KOLs often post a few times a day; too-tight windows make X look "empty".
    "twitter": 720,
    "reddit": 45,
    "rss": 45,
    "youtube": 120,
    "web": 45,
    "v2ex": 45,
    "bilibili": 120,
    "xiaohongshu": 45,
    "github": 180,
}


def visible_blob(text: str | None, raw_json: dict[str, Any] | None = None) -> str:
    """Human-visible fields only — never the full JSON payload (V2EX has a `btc` key)."""
    parts: list[str] = []
    payload = raw_json if isinstance(raw_json, dict) else {}
    for key in ("title", "title_original", "text_original"):
        value = payload.get(key)
        if value:
            parts.append(str(value))
    if text:
        parts.append(text)
    return " ".join(parts)


def mentions_btc(text: str | None, settings: Settings, *, raw_json: dict[str, Any] | None = None) -> bool:
    blob = visible_blob(text, raw_json)
    if not blob:
        return False
    for query in settings.attention_queries:
        needle = (query or "").strip()
        if not needle:
            continue
        if _CJK_QUERY.search(needle):
            if needle in blob:
                return True
            continue
        if needle.startswith("$"):
            pattern = re.escape(needle)
        else:
            pattern = rf"(?<![A-Za-z0-9]){re.escape(needle)}(?![A-Za-z0-9])"
        if re.search(pattern, blob, flags=re.IGNORECASE):
            return True
    return False


def max_age_minutes_for(platform: str, settings: Settings) -> int:
    default = int(getattr(settings.ingest, "max_age_minutes", 45) or 45)
    return int(_PLATFORM_MAX_AGE_MINUTES.get(platform.lower(), default))


def is_fresh(
    event_ts: datetime | None,
    settings: Settings,
    *,
    platform: str | None = None,
) -> bool:
    if event_ts is None:
        return False
    minutes = max_age_minutes_for(platform or "", settings) if platform else int(
        getattr(settings.ingest, "max_age_minutes", 45) or 45
    )
    if minutes <= 0:
        return True
    age = utcnow() - to_utc(event_ts)
    return age <= timedelta(minutes=minutes)


def keep_attention_post(post: RawPost, settings: Settings) -> bool:
    raw = post.raw_json if isinstance(post.raw_json, dict) else {}
    is_kol = bool(raw.get("author_influence"))
    # KOL watchlist posts are kept even when they are not about BTC.
    # Everyone else must mention BTC / Bitcoin / configured aliases.
    if not is_kol and not mentions_btc(post.text, settings, raw_json=post.raw_json):
        return False
    # YouTube flat search often only has YYYYMMDD (midnight) — too coarse for live trading.
    if post.platform == "youtube" and raw.get("upload_date") and not raw.get("timestamp"):
        return False
    return is_fresh(post.event_ts, settings, platform=post.platform)


def localize_post(post: RawPost) -> RawPost:
    """Translate CJK title/body to English; keep the original in raw_json."""
    extra = dict(post.raw_json or {})
    title = str(extra.get("title") or "").strip()
    updates: dict[str, Any] = {}
    if has_cjk(title):
        extra.setdefault("title_original", title)
        extra["title"] = translate_to_english(title)
        updates["raw_json"] = extra
    if has_cjk(post.text):
        extra.setdefault("text_original", post.text)
        translated = translate_to_english(post.text)
        extra["text_en"] = translated
        updates["text"] = translated
        updates["raw_json"] = extra
    if not updates:
        return post
    return post.model_copy(update=updates)
