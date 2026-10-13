"""Color-coded BTC source lines for the terminal (brand colors)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from rich.console import Console
from rich.text import Text

from btcpoly.config import Settings
from btcpoly.db.models import RawPostRow
from btcpoly.filter.attention import mentions_btc
from btcpoly.text.translate import has_cjk, translate_to_english
from btcpoly.timeutil import to_utc, utcnow

PACIFIC = ZoneInfo("America/Los_Angeles")

# Brand-ish colors. YouTube logo is red — label and title render red.
PLATFORM_STYLE = {
    "youtube": "bold bright_red",
    "twitter": "bold bright_cyan",
    "reddit": "bold #FF4500",
    "github": "bold white",
    "bilibili": "bold hot_pink",
    "xiaohongshu": "bold red",
    "rss": "bold gold1",
    "web": "bold green",
    "v2ex": "bold chartreuse3",
}

PLATFORM_ICON = {
    "youtube": "▶",
    "twitter": "𝕏",
    "reddit": "●",
    "github": "⌥",
    "bilibili": "▶",
    "xiaohongshu": "✿",
    "rss": "☰",
    "web": "◎",
    "v2ex": "◆",
}

TITLE_MATCHES_BRAND = {"youtube", "xiaohongshu", "reddit", "bilibili"}


@dataclass
class SourceHeadline:
    platform: str
    title: str
    author: str | None = None
    url: str | None = None
    influence: bool = False
    event_ts: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "title": self.title,
            "author": self.author,
            "url": self.url,
            "influence": self.influence,
            "event_ts": self.event_ts.isoformat() if self.event_ts else None,
        }


def format_event_time(event_ts: datetime | None) -> str:
    if event_ts is None:
        return "????"
    ts = to_utc(event_ts).astimezone(PACIFIC)
    age = utcnow() - to_utc(event_ts)
    minutes = max(0, int(age.total_seconds() // 60))
    if minutes < 1:
        age_label = "now"
    elif minutes < 60:
        age_label = f"{minutes}m"
    else:
        age_label = f"{minutes // 60}h"
    return f"{ts.strftime('%H:%M')}PST {age_label:>4}"


def source_url(
    platform: str,
    url: str | None,
    *,
    post_id: str | None = None,
    author: str | None = None,
    raw_json: dict[str, Any] | None = None,
) -> str | None:
    """Best clickable URL for a mention."""
    if url and str(url).startswith(("http://", "https://")):
        return str(url)
    payload = raw_json or {}
    for key in ("webpage_url", "html_url", "url", "link", "permalink"):
        value = payload.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    pid = str(post_id or payload.get("id") or "").strip()
    handle = (author or "").lstrip("@")
    plat = platform.lower()
    if plat == "youtube" and pid:
        return f"https://www.youtube.com/watch?v={pid}"
    if plat == "twitter" and pid and pid.isdigit():
        if handle:
            return f"https://x.com/{handle}/status/{pid}"
        return f"https://x.com/i/web/status/{pid}"
    if plat == "reddit" and pid:
        # opencli ids are often bare; permalink preferred when present
        return f"https://www.reddit.com/{pid.lstrip('/')}" if pid.startswith(("r/", "http")) else f"https://redd.it/{pid}"
    if plat == "github" and pid and "/" in pid:
        return f"https://github.com/{pid}"
    if plat == "v2ex" and pid:
        return f"https://www.v2ex.com/t/{pid}"
    return None


def headline_from_post(
    platform: str,
    text: str | None,
    author: str | None = None,
    url: str | None = None,
    raw_json: dict[str, Any] | None = None,
    event_ts: datetime | None = None,
) -> SourceHeadline:
    payload = raw_json or {}
    title = str(payload.get("title") or "").strip()
    if not title and text:
        title = text.strip().splitlines()[0].strip()
    if not title:
        title = url or "(no title)"
    title = " ".join(title.split())
    if has_cjk(title):
        title = translate_to_english(title)
    if len(title) > 120:
        title = title[:117] + "..."
    channel = (
        author
        or payload.get("uploader")
        or payload.get("channel")
        or payload.get("author")
        or None
    )
    if isinstance(channel, dict):
        channel = channel.get("screenName") or channel.get("name") or channel.get("username")
    if channel is not None:
        channel = str(channel).strip() or None
    influence = bool(payload.get("author_influence"))
    resolved = source_url(
        platform,
        url,
        post_id=str(payload.get("id") or "") or None,
        author=channel,
        raw_json=payload,
    )
    return SourceHeadline(
        platform=platform,
        title=title,
        author=channel,
        url=resolved,
        influence=influence,
        event_ts=to_utc(event_ts) if event_ts is not None else None,
    )


def headline_from_row(row: RawPostRow) -> SourceHeadline:
    raw = row.raw_json if isinstance(row.raw_json, dict) else {}
    return headline_from_post(
        row.platform,
        row.text,
        row.author,
        row.url,
        {**raw, "id": raw.get("id") or row.post_id},
        event_ts=row.event_ts,
    )


def headline_key(headline: SourceHeadline) -> str:
    return headline.url or f"{headline.platform}:{headline.author}:{headline.title}"


def sort_headlines(
    headlines: list[SourceHeadline],
    *,
    newest_first: bool = False,
) -> list[SourceHeadline]:
    def key(item: SourceHeadline) -> datetime:
        if item.event_ts is None:
            return datetime.min.replace(tzinfo=utcnow().tzinfo)
        return to_utc(item.event_ts)

    return sorted(headlines, key=key, reverse=newest_first)


def style_for(platform: str) -> str:
    return PLATFORM_STYLE.get(platform.lower(), "bold white")


def render_source_line(headline: SourceHeadline) -> Text:
    platform = headline.platform.lower()
    style = style_for(platform)
    title_style = style if platform in TITLE_MATCHES_BRAND else "white"
    icon = PLATFORM_ICON.get(platform, "•")
    line = Text()
    line.append(f"{format_event_time(headline.event_ts):<16}", style="dim")
    line.append(f"{icon} {headline.platform.upper():<10}", style=style)
    if headline.influence:
        line.append("KOL ", style="bold yellow")
    creator = headline.author or "unknown"
    line.append(f"{creator}  ", style="dim")
    if headline.url:
        # Windows Terminal / modern consoles: Ctrl+click (or click) opens the link.
        line.append(headline.title, style=f"{title_style} link {headline.url}")
        line.append("  ", style="dim")
        line.append("open", style=f"dim underline link {headline.url}")
    else:
        line.append(headline.title, style=title_style)
    return line


def print_source_feed(
    console: Console,
    headlines: list[SourceHeadline],
    *,
    heading: str = "BTC mentions",
) -> None:
    console.print()
    console.print(f"[bold]{heading}[/bold]")
    if not headlines:
        console.print("  [dim]none this run[/dim]")
        return
    for item in sort_headlines(headlines, newest_first=True):
        console.print(render_source_line(item))


def recent_headlines(
    session,
    settings: Settings | None = None,
    *,
    limit: int = 20,
) -> list[SourceHeadline]:
    from sqlalchemy import desc, select

    from btcpoly.filter.attention import is_fresh

    rows = session.scalars(
        select(RawPostRow).order_by(desc(RawPostRow.event_ts)).limit(max(limit * 12, 60))
    ).all()
    headlines: list[SourceHeadline] = []
    for row in rows:
        raw = row.raw_json if isinstance(row.raw_json, dict) else {}
        if settings is not None:
            if not is_fresh(row.event_ts, settings, platform=row.platform):
                continue
            original = str(raw.get("title_original") or raw.get("text_original") or "")
            if not mentions_btc(row.text, settings, raw_json=raw) and not mentions_btc(
                original, settings, raw_json=raw
            ):
                continue
        headlines.append(headline_from_row(row))
        if len(headlines) >= limit:
            break
    return sort_headlines(headlines, newest_first=True)
