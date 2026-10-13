"""Tolerant mapping of heterogeneous CLI/HTTP payloads to RawPost."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from btcpoly.ingestion.schema import RawPost
from btcpoly.timeutil import parse_ts, utcnow


def _stable_id(*parts: Any) -> str:
    raw = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:24]


def _first(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
        nested = item
        ok = True
        for part in key.split("."):
            if isinstance(nested, dict) and part in nested:
                nested = nested[part]
            else:
                ok = False
                break
        if ok and nested not in (None, ""):
            return nested
    return None


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _as_ts(value: Any, *, fallback_now: bool = True) -> datetime:
    """Parse a timestamp. Never silently rewrite a bad date to 'now' (that breaks freshness)."""
    if value in (None, ""):
        if fallback_now:
            return utcnow()
        raise ValueError("missing timestamp")
    return parse_ts(value)


def _text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text[:8000]
    return None


def _url(item: dict[str, Any], *keys: str) -> str | None:
    value = _first(item, *keys)
    if value:
        return str(value)
    return None


def _author(item: dict[str, Any]) -> str | None:
    value = _first(
        item,
        "author",
        "uploader",
        "login",
        "username",
        "user",
        "owner.login",
        "member.username",
        "user.screen_name",
        "user.username",
    )
    if isinstance(value, dict):
        return _first(value, "login", "username", "screen_name", "screenName", "name")
    if value:
        return str(value)
    return None


def normalize_generic(platform: str, item: dict[str, Any], *, fallback_text: str | None = None) -> RawPost:
    post_id = _first(
        item,
        "id",
        "id_str",
        "post_id",
        "fullName",
        "full_name",
        "guid",
        "link",
        "url",
        "webpage_url",
    )
    url = _url(item, "webpage_url", "html_url", "url", "link", "permalink")
    if post_id is None:
        post_id = _stable_id(platform, url, _first(item, "title", "text", "description"))
    text = _text(
        _first(item, "text", "full_text", "title", "description", "content", "body", "summary"),
        fallback_text,
    )
    author = _author(item)
    if author is None:
        author = _first(item, "author.screenName", "author.screen_name", "author.username", "retweetedBy")
        if author is not None:
            author = str(author)
    return RawPost(
        platform=platform,
        post_id=str(post_id),
        author=author,
        event_ts=_as_ts(
            _first(
                item,
                "timestamp",
                "created",
                "created_utc",
                "created_at",
                "createdAtISO",
                "createdAt",
                "updatedAt",
                "published",
                "published_parsed",
                "upload_date",
            )
        ),
        text=text,
        views=_as_int(_first(item, "view_count", "views", "play", "metrics.views")),
        likes=_as_int(
            _first(item, "like_count", "likes", "favorite_count", "metrics.likes", "score", "upvotes")
        ),
        replies=_as_int(
            _first(item, "reply_count", "replies", "comment_count", "comments", "metrics.replies")
        ),
        reposts=_as_int(_first(item, "retweet_count", "reposts", "forward", "metrics.retweets")),
        author_followers=_as_int(
            _first(item, "author_followers", "followers", "user.followers_count", "owner.followers")
        ),
        url=url,
        raw_json=item if isinstance(item, dict) else {"value": item},
    )


def normalize_youtube(item: dict[str, Any]) -> RawPost:
    post = normalize_generic("youtube", item)
    # Prefer real unix timestamps from a full yt-dlp dump (not day-only upload_date).
    for key in ("timestamp", "release_timestamp"):
        value = item.get(key)
        if value not in (None, "", 0):
            try:
                return post.model_copy(
                    update={
                        "event_ts": parse_ts(value),
                        "url": post.url or f"https://www.youtube.com/watch?v={post.post_id}",
                    }
                )
            except (TypeError, ValueError):
                continue
    # Day-level upload_date alone is kept for debugging but freshness will reject it.
    if item.get("upload_date"):
        try:
            post = post.model_copy(update={"event_ts": parse_ts(item["upload_date"])})
        except (TypeError, ValueError):
            pass
    if not post.url and post.post_id:
        post = post.model_copy(update={"url": f"https://www.youtube.com/watch?v={post.post_id}"})
    return post


def normalize_github(item: dict[str, Any]) -> RawPost:
    post = normalize_generic("github", item)
    if not post.url and post.post_id and "/" in str(post.post_id):
        post.url = f"https://github.com/{post.post_id}"
    return post


def normalize_v2ex(item: dict[str, Any]) -> RawPost:
    return normalize_generic("v2ex", item)


def _rss_published_ts(entry: dict[str, Any]) -> datetime | None:
    """Prefer feedparser's struct_time fields; then RFC-2822 / ISO strings. No 'now' fallback."""
    for key in (
        "published_parsed",
        "updated_parsed",
        "created_parsed",
        "published",
        "updated",
        "created",
        "date",
    ):
        value = entry.get(key)
        if value in (None, "", 0):
            continue
        try:
            return parse_ts(value)
        except (TypeError, ValueError):
            continue
    return None


def _strip_html(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", text)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"&\w+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _rss_body(entry: dict[str, Any]) -> str:
    """Best available body from the feed item (not a full page scrape)."""
    chunks: list[str] = []
    content = entry.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("value"):
                chunks.append(_strip_html(block.get("value")))
            elif block:
                chunks.append(_strip_html(block))
    for key in ("content:encoded", "summary", "description", "subtitle"):
        val = entry.get(key)
        if val:
            chunks.append(_strip_html(val))
    # Deduplicate while preferring longer text first.
    chunks = sorted({c for c in chunks if c}, key=len, reverse=True)
    if not chunks:
        return ""
    # Cap so one wire dump cannot explode features.
    return chunks[0][:6000]


def normalize_rss_entry(entry: dict[str, Any], feed_url: str) -> RawPost | None:
    """Map an RSS item. Returns None when the publish time is missing/unusable."""
    from btcpoly.attention.credibility import source_weight

    payload = dict(entry)
    payload.setdefault("feed_url", feed_url)
    event_ts = _rss_published_ts(payload)
    if event_ts is None:
        return None
    payload["published"] = event_ts.isoformat()
    # Avoid normalize_generic falling back to utcnow via unrelated empty date keys.
    for noise in ("timestamp", "created_at", "createdAt", "updatedAt", "createdAtISO"):
        payload.pop(noise, None)

    title = _strip_html(_first(payload, "title") or "")
    body = _rss_body(payload)
    # Prefer title + body so sentiment sees more than the headline alone.
    if title and body:
        combined = f"{title}\n\n{body}"
    else:
        combined = title or body or None
    payload["title"] = title
    payload["summary"] = body
    payload["body"] = body
    payload["text"] = combined

    post = normalize_generic("rss", payload)
    article_url = post.url
    weight = source_weight(feed_url=feed_url, article_url=article_url)
    extra = dict(post.raw_json or {})
    extra.update(
        {
            "feed_url": feed_url,
            "title": title,
            "summary": body,
            "body": body,
            "source_weight": weight,
        }
    )
    return post.model_copy(
        update={
            "event_ts": event_ts,
            "text": combined,
            "raw_json": extra,
            "author": post.author or urlparse(feed_url).netloc or "rss",
        }
    )


def normalize_web_page(url: str, markdown: str) -> RawPost:
    host = urlparse(url).netloc or "web"
    return RawPost(
        platform="web",
        post_id=_stable_id(url),
        author=host,
        event_ts=utcnow(),
        text=_text(markdown),
        url=url,
        raw_json={"url": url, "source": "jina"},
    )


def coerce_items(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [x if isinstance(x, dict) else {"text": x} for x in payload]
    if isinstance(payload, dict):
        for key in ("data", "items", "results", "entries", "tweets", "repos"):
            nested = payload.get(key)
            if isinstance(nested, list):
                return coerce_items(nested)
        return [payload]
    return [{"text": payload}]


def dumps_safe(value: Any) -> str:
    return json.dumps(value, default=str)
