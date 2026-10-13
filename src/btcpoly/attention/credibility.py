"""Source credibility weights for attention / sentiment (RSS-first)."""

from __future__ import annotations

from urllib.parse import urlparse

# Trusted ingest floor: only Tier A/B hosts clear this (see is_trusted_source).
TRUSTED_MIN_WEIGHT = 1.15

# Higher = slightly stronger pull on sentiment_net and weighted mention mass.
# Keep the range modest so one outlet cannot dominate the book.
_HOST_WEIGHTS: dict[str, float] = {
    # Tier A — major finance / world desks
    "ft.com": 1.45,
    "www.ft.com": 1.45,
    "bloomberg.com": 1.45,
    "www.bloomberg.com": 1.45,
    "feeds.bloomberg.com": 1.45,
    "wsj.com": 1.45,
    "www.wsj.com": 1.45,
    "feeds.content.dowjones.io": 1.45,
    "nytimes.com": 1.40,
    "www.nytimes.com": 1.40,
    "rss.nytimes.com": 1.40,
    "economist.com": 1.40,
    "www.economist.com": 1.40,
    "reuters.com": 1.40,
    "www.reuters.com": 1.40,
    "apnews.com": 1.40,
    "www.apnews.com": 1.40,
    "bbc.co.uk": 1.35,
    "www.bbc.co.uk": 1.35,
    "bbc.com": 1.35,
    "www.bbc.com": 1.35,
    "feeds.bbci.co.uk": 1.35,
    # Tier B — strong business / reputable crypto desks
    "coindesk.com": 1.30,
    "www.coindesk.com": 1.30,
    "theblock.co": 1.25,
    "www.theblock.co": 1.25,
    "blockworks.co": 1.20,
    "www.blockworks.co": 1.20,
    "dlnews.com": 1.20,
    "www.dlnews.com": 1.20,
    "cnbc.com": 1.25,
    "www.cnbc.com": 1.25,
    "washingtonpost.com": 1.25,
    "www.washingtonpost.com": 1.25,
    "feeds.washingtonpost.com": 1.25,
    "theguardian.com": 1.20,
    "www.theguardian.com": 1.20,
    "npr.org": 1.20,
    "feeds.npr.org": 1.20,
    "axios.com": 1.20,
    "api.axios.com": 1.20,
    "semafor.com": 1.15,
    "www.semafor.com": 1.15,
    "marketwatch.com": 1.15,
    "feeds.marketwatch.com": 1.15,
    "www.marketwatch.com": 1.15,
    # Tier B — major US broadcast / consumer finance
    "cnn.com": 1.20,
    "www.cnn.com": 1.20,
    "rss.cnn.com": 1.20,
    "foxnews.com": 1.15,
    "www.foxnews.com": 1.15,
    "moxie.foxnews.com": 1.15,
    "foxbusiness.com": 1.15,
    "www.foxbusiness.com": 1.15,
    "moxie.foxbusiness.com": 1.15,
    "nbcnews.com": 1.20,
    "www.nbcnews.com": 1.20,
    "feeds.nbcnews.com": 1.20,
    "cbsnews.com": 1.20,
    "www.cbsnews.com": 1.20,
    "abcnews.go.com": 1.20,
    "feeds.abcnews.com": 1.20,
    "abcnews.com": 1.20,
    "finance.yahoo.com": 1.15,
    "feeds.finance.yahoo.com": 1.15,
    "yahoo.com": 1.15,
    "forbes.com": 1.15,
    "www.forbes.com": 1.15,
    "businessinsider.com": 1.15,
    "www.businessinsider.com": 1.15,
    "markets.businessinsider.com": 1.15,
    "usatoday.com": 1.15,
    "www.usatoday.com": 1.15,
    # Google News is only used with site: filters for majors above.
    "news.google.com": 1.15,
    # Below floor — kept only so old DB rows / tests still resolve weights.
    "bitcoinmagazine.com": 1.05,
    "cointelegraph.com": 0.90,
    "decrypt.co": 0.90,
    "seekingalpha.com": 0.85,
    "techcrunch.com": 0.80,
    "cryptoslate.com": 0.50,
    "cryptopotato.com": 0.50,
    "newsbtc.com": 0.45,
    "www.newsbtc.com": 0.45,
    "bitcoinist.com": 0.45,
    "www.bitcoinist.com": 0.45,
    "cryptopolitan.com": 0.40,
    "www.cryptopolitan.com": 0.40,
    "crypto.news": 0.40,
    "u.today": 0.40,
    "ambcrypto.com": 0.40,
    "beincrypto.com": 0.40,
    "news.bitcoin.com": 0.50,
}


def host_from_url(url: str | None) -> str:
    if not url:
        return ""
    host = (urlparse(str(url)).netloc or "").strip().lower()
    if host.startswith("www."):
        # Keep both www and apex in the table; normalize lookup below.
        pass
    return host


def source_weight(*, feed_url: str | None = None, article_url: str | None = None) -> float:
    """Credibility weight. Unknown hosts default low (not trusted for RSS)."""
    for url in (feed_url, article_url):
        host = host_from_url(url)
        if not host:
            continue
        if host in _HOST_WEIGHTS:
            return float(_HOST_WEIGHTS[host])
        # Strip www. and retry
        bare = host[4:] if host.startswith("www.") else host
        if bare in _HOST_WEIGHTS:
            return float(_HOST_WEIGHTS[bare])
        # Parent domain match (e.g. markets.businessinsider.com)
        parts = bare.split(".")
        if len(parts) >= 2:
            parent = ".".join(parts[-2:])
            if parent in _HOST_WEIGHTS:
                return float(_HOST_WEIGHTS[parent])
    return 0.5


def is_trusted_source(*, feed_url: str | None = None, article_url: str | None = None) -> bool:
    """True only for major Tier A/B outlets used for live RSS ingest."""
    return source_weight(feed_url=feed_url, article_url=article_url) >= TRUSTED_MIN_WEIGHT
