"""Translate CJK headlines to English. Original text is kept when translation fails."""

from __future__ import annotations

import json
import re
from urllib.parse import quote
from urllib.request import Request, urlopen

_CJK = re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_CACHE: dict[str, str] = {}
_MAX_CHARS = 500
_UA = "Mozilla/5.0 (compatible; btcpoly/0.1; research)"


def has_cjk(text: str | None) -> bool:
    return bool(_CJK.search(text or ""))


def translate_to_english(text: str | None, *, timeout: int = 12) -> str:
    """Return English text when the input contains CJK; otherwise return it unchanged."""
    original = " ".join((text or "").split())
    if not original:
        return ""
    if not has_cjk(original):
        return original
    cached = _CACHE.get(original)
    if cached:
        return cached
    excerpt = original[:_MAX_CHARS]
    translated = _google(excerpt, timeout) or _mymemory(excerpt, timeout)
    if not translated or translated == excerpt:
        return original
    _CACHE[original] = translated
    return translated


def _google(text: str, timeout: int) -> str | None:
    url = (
        "https://translate.googleapis.com/translate_a/single"
        f"?client=gtx&sl=auto&tl=en&dt=t&q={quote(text)}"
    )
    raw = _http_json(url, timeout)
    if not isinstance(raw, list) or not raw:
        return None
    chunks = raw[0]
    if not isinstance(chunks, list):
        return None
    parts: list[str] = []
    for chunk in chunks:
        if isinstance(chunk, list) and chunk and isinstance(chunk[0], str):
            parts.append(chunk[0])
    out = "".join(parts).strip()
    return out or None


def _mymemory(text: str, timeout: int) -> str | None:
    url = (
        "https://api.mymemory.translated.net/get"
        f"?q={quote(text)}&langpair=zh|en"
    )
    raw = _http_json(url, timeout)
    if not isinstance(raw, dict):
        return None
    data = raw.get("responseData")
    if not isinstance(data, dict):
        return None
    out = str(data.get("translatedText") or "").strip()
    if not out or "MYMEMORY WARNING" in out.upper():
        return None
    return out


def _http_json(url: str, timeout: int) -> object | None:
    req = Request(url, headers={"User-Agent": _UA})
    try:
        with urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
        return json.loads(body)
    except Exception:
        return None
