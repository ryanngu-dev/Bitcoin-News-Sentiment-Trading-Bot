"""Human-readable trade rationale (why this paper decision fired)."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus, urlparse


def _pct(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "—"
    x = float(value) * 100.0
    if signed:
        return f"{x:+.1f}%"
    return f"{x:.1f}%"


def _kalshi_market_url(slug: str | None) -> str | None:
    if not slug:
        return None
    s = str(slug).strip()
    if not s:
        return None
    # Series hub is always valid; ticker pages use the full market ticker as slug.
    if s.upper() == "KXBTC15M":
        return "https://kalshi.com/markets/kxbtc15m"
    # Prefer the short form Kalshi uses in share links (drop trailing -MM when present).
    parts = s.split("-")
    if len(parts) >= 3 and parts[-1].isdigit() and len(parts[-1]) <= 2:
        s = "-".join(parts[:-1])
    return f"https://kalshi.com/markets/kxbtc15m/bitcoin-price-up-down/{s.lower()}"


def clickable_url(url: str | None, *, title: str | None = None) -> str | None:
    """Return a browser-openable URL. Opaque Google News article links are rewritten."""
    text = str(url or "").strip()
    if not text.startswith(("http://", "https://")):
        return None
    host = (urlparse(text).netloc or "").lower()
    path = urlparse(text).path or ""
    # Google News RSS article IDs are not stable share links in many browsers.
    if "news.google.com" in host and ("/rss/articles" in path or "/articles/" in path):
        q = " ".join(str(title or "").split())
        if q:
            return f"https://news.google.com/search?q={quote_plus(q)}&hl=en-US&gl=US&ceid=US:en"
        return None
    return text


def build_trade_rationale(payload: dict[str, Any]) -> dict[str, Any]:
    """Short why + bullet evidence + clickable links for a BUY decision."""
    decision = str(payload.get("decision") or "")
    side = "UP" if decision == "BUY_UP" else ("DOWN" if decision == "BUY_DOWN" else "NONE")
    feats = payload.get("features") if isinstance(payload.get("features"), dict) else {}
    edge = payload.get("edge")
    p_model = payload.get("p_up_model")
    p_mkt = payload.get("p_up_market")
    ret = payload.get("btc_ret")
    attn = feats.get("attn_z_900", payload.get("attn_z_900"))
    sent = feats.get("sentiment_net_900", payload.get("sentiment_net_900"))
    n900 = feats.get("mention_count_900")

    bullets: list[str] = []
    if p_model is not None and p_mkt is not None:
        line = f"Model P(UP) {_pct(float(p_model))} vs Kalshi {_pct(float(p_mkt))}"
        if edge is not None:
            line += f"  →  edge {_pct(float(edge), signed=True)}"
        bullets.append(line)
    if ret is not None:
        direction = "up" if float(ret) > 0 else ("down" if float(ret) < 0 else "flat")
        bullets.append(f"BTC ~60s move {direction} ({_pct(float(ret), signed=True)})")
    if attn is not None:
        z = float(attn)
        heat = "hot" if z >= 1.0 else ("quiet" if z <= -0.5 else "normal")
        extra = f", {n900} posts in 15m" if n900 is not None else ""
        bullets.append(f"Mention volume {heat} (attn_z {z:+.1f}{extra})")
    if sent is not None:
        s = float(sent)
        lean = "bullish" if s > 0.05 else ("bearish" if s < -0.05 else "mixed")
        bullets.append(f"Post consensus {lean} (sentiment_net {s:+.2f})")
    ai = feats.get("ai_sentiment_net_900", payload.get("ai_sentiment_net_900"))
    ai_n = feats.get("ai_sentiment_scored_900", payload.get("ai_sentiment_scored_900"))
    if ai is not None and int(ai_n or 0) > 0:
        a = float(ai)
        lean = "bullish" if a > 0.05 else ("bearish" if a < -0.05 else "mixed")
        cred = feats.get("ai_credibility_mean_900", payload.get("ai_credibility_mean_900"))
        cred_bit = f", cred={float(cred):.2f}" if cred is not None else ""
        bullets.append(f"AI lean {lean} (ai_net {a:+.2f} on {int(ai_n)} posts{cred_bit})")

    if side == "UP":
        lead = "Buying UP — model P(UP) is above Kalshi."
    elif side == "DOWN":
        lead = "Buying DOWN — model P(UP) is below Kalshi."
    else:
        lead = "No trade."

    # Back-compat one-liner for anything that still reads `summary` only.
    summary = lead
    if bullets:
        summary = lead + " " + " | ".join(bullets)

    links: list[dict[str, str]] = []
    market_url = _kalshi_market_url(str(payload.get("slug") or "") or None)
    if market_url:
        links.append(
            {
                "label": f"Kalshi {payload.get('slug')}",
                "url": market_url,
            }
        )

    sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []
    ranked = sorted(
        [s for s in sources if isinstance(s, dict)],
        key=lambda s: (
            "news.google.com" in str(s.get("url") or "").lower(),  # prefer direct publisher URLs
            not bool(s.get("influence")),
            not bool(s.get("url")),
        ),
    )
    for item in ranked:
        title = str(item.get("title") or "").strip().replace("\n", " ")
        url = clickable_url(str(item.get("url") or "").strip() or None, title=title)
        if not url:
            continue
        plat = str(item.get("platform") or "?").upper()
        author = str(item.get("author") or "").strip()
        short = title
        if len(short) > 64:
            short = short[:61] + "…"
        label = plat
        if author:
            label += f" @{author}" if not author.startswith("@") else f" {author}"
        if short:
            label += f" — {short}"
        links.append({"label": label, "url": url})
        if len(links) >= 5:  # market + up to 4 sources
            break

    return {
        "summary": summary,
        "lead": lead,
        "bullets": bullets,
        "side": side,
        "links": links,
    }
