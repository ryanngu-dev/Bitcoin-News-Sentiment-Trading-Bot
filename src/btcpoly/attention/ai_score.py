"""LLM short-horizon BTC lean scores for recent posts (OpenAI-compatible APIs)."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from btcpoly.attention.credibility import source_weight
from btcpoly.attention.sentiment import post_blob
from btcpoly.config import Settings
from btcpoly.db.models import RawPostRow, SentimentRow
from btcpoly.logging import get_logger
from btcpoly.timeutil import to_utc, utcnow

log = get_logger(__name__)

METHOD = "llm_v1"
_JSON_BLOCK = re.compile(r"\{[\s\S]*\}")


@dataclass(frozen=True)
class AiPostScore:
    raw_post_id: int
    score: float  # [-1, 1] BTC lean
    credibility: float  # [0, 1] source/claim trust for short-horizon trading
    label: str
    reason: str


def resolve_ai_endpoint(settings: Settings) -> tuple[str, str, str] | None:
    """Return (base_url, api_key, model) or None if AI scoring is off / unconfigured."""
    ai = settings.ai_sentiment
    if not ai.enabled:
        return None
    provider = (ai.provider or "auto").strip().lower()
    groq_key = (os.environ.get("GROQ_API_KEY") or "").strip()
    openai_key = (os.environ.get("OPENAI_API_KEY") or "").strip()

    if provider == "auto":
        if groq_key:
            provider = "groq"
        elif openai_key:
            provider = "openai"
        else:
            return None
    if provider == "groq":
        if not groq_key:
            return None
        model = ai.model or "openai/gpt-oss-20b"
        return ("https://api.groq.com/openai/v1", groq_key, model)
    if provider == "openai":
        if not openai_key:
            return None
        model = ai.model or "gpt-4o-mini"
        return ("https://api.openai.com/v1", openai_key, model)
    return None


def _clip_score(value: Any) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(-1.0, min(1.0, x))


def _clip_cred(value: Any, *, default: float = 0.5) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, x))


def _label_from_score(score: float) -> str:
    if score > 0.15:
        return "bullish"
    if score < -0.15:
        return "bearish"
    return "neutral"


def _post_priority(row: RawPostRow) -> tuple[int, float]:
    raw = row.raw_json if isinstance(row.raw_json, dict) else {}
    influence = 1 if raw.get("author_influence") else 0
    w = raw.get("source_weight")
    if w is None:
        w = source_weight(feed_url=str(raw.get("feed_url") or "") or None, article_url=row.url)
    return (influence, float(w))


def _build_prompt(items: list[tuple[str, str, str]]) -> str:
    lines = [
        "You score crypto headlines/posts for near-term Bitcoin trading (~next 15 minutes).",
        "For each item return:",
        "- score in [-1,1]: -1=bearish for BTC price, 0=irrelevant/neutral, +1=bullish",
        "- credibility in [0,1]: how trustworthy/useful this source+claim is for short-horizon BTC",
        "  (1.0=major desk / clear primary signal, 0.5=mixed, 0.1=spam/promo/low-quality blog)",
        "Down-rank ads, merch, shill coins, recycled SEO blogs, and vague hype.",
        'JSON only: {"scores":[{"id":"...","score":0.0,"credibility":0.5,"reason":"<=12 words"}]}',
        "",
        "Items:",
    ]
    for pid, source, text in items:
        clean = " ".join(text.split())
        if len(clean) > 480:
            clean = clean[:477] + "..."
        lines.append(f"- id={pid} source={source} text={clean}")
    return "\n".join(lines)


def _parse_scores(
    payload: str, wanted_ids: set[str]
) -> dict[str, tuple[float, float, str]]:
    text = (payload or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    match = _JSON_BLOCK.search(text)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    rows = data.get("scores") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return {}
    out: dict[str, tuple[float, float, str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        pid = str(row.get("id") or "").strip()
        if not pid or (wanted_ids and pid not in wanted_ids):
            continue
        score = _clip_score(row.get("score"))
        cred = _clip_cred(row.get("credibility"), default=0.5)
        reason = str(row.get("reason") or "").strip().replace("\n", " ")
        if len(reason) > 80:
            reason = reason[:77] + "..."
        out[pid] = (score, cred, reason)
    return out


HttpPostFn = Callable[[str, dict[str, str], bytes, float], str]


def _default_http_post(url: str, headers: dict[str, str], body: bytes, timeout: float) -> str:
    merged = {
        "User-Agent": "btcpoly/0.1",
        **headers,
    }
    req = urllib.request.Request(url, data=body, headers=merged, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code} {exc.reason}: {detail}") from None


def call_chat_completions(
    *,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    timeout: float,
    http_post: HttpPostFn | None = None,
) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    body = json.dumps(
        {
            "model": model,
            "temperature": 0.1,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a careful BTC short-horizon news scorer. JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
        }
    ).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    poster = http_post or _default_http_post
    raw = poster(url, headers, body, timeout)
    data = json.loads(raw)
    choices = data.get("choices") if isinstance(data, dict) else None
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return ""
    return str(message.get("content") or "")


def select_posts_for_ai(
    session: Session,
    *,
    as_of: datetime,
    lookback_seconds: int,
    limit: int,
) -> list[RawPostRow]:
    end = to_utc(as_of)
    start = end - timedelta(seconds=int(lookback_seconds))
    rows = list(
        session.scalars(
            select(RawPostRow)
            .where(RawPostRow.event_ts >= start, RawPostRow.event_ts <= end)
            .order_by(RawPostRow.event_ts.desc())
            .limit(max(limit * 4, 40))
        ).all()
    )
    if not rows:
        return []
    ids = [int(r.id) for r in rows]
    already = set(
        session.scalars(
            select(SentimentRow.raw_post_id).where(
                SentimentRow.raw_post_id.in_(ids),
                SentimentRow.method == METHOD,
            )
        ).all()
    )
    candidates = [r for r in rows if int(r.id) not in already]
    candidates.sort(
        key=lambda r: (
            _post_priority(r)[0],
            _post_priority(r)[1],
            to_utc(r.event_ts).timestamp() if r.event_ts else 0.0,
        ),
        reverse=True,
    )
    return candidates[: max(0, int(limit))]


def score_posts_with_llm(
    posts: list[RawPostRow],
    settings: Settings,
    *,
    http_post: HttpPostFn | None = None,
) -> list[AiPostScore]:
    endpoint = resolve_ai_endpoint(settings)
    if endpoint is None or not posts:
        return []
    base_url, api_key, model = endpoint
    items: list[tuple[str, str, str]] = []
    for row in posts:
        raw = row.raw_json if isinstance(row.raw_json, dict) else {}
        blob = post_blob(row.text, raw)
        if not blob.strip():
            continue
        source = str(row.author or raw.get("feed_url") or row.platform or "unknown")
        items.append((str(row.id), source, blob))
    if not items:
        return []
    prompt = _build_prompt(items)
    try:
        content = call_chat_completions(
            base_url=base_url,
            api_key=api_key,
            model=model,
            prompt=prompt,
            timeout=float(settings.ai_sentiment.timeout_seconds),
            http_post=http_post,
        )
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, RuntimeError) as exc:
        log.warning("ai sentiment request failed: %s", exc)
        return []
    parsed = _parse_scores(content, {pid for pid, _, _ in items})
    out: list[AiPostScore] = []
    for row in posts:
        hit = parsed.get(str(row.id))
        if hit is None:
            continue
        score, cred, reason = hit
        out.append(
            AiPostScore(
                raw_post_id=int(row.id),
                score=score,
                credibility=cred,
                label=_label_from_score(score),
                reason=reason,
            )
        )
    return out


def persist_ai_scores(session: Session, scores: list[AiPostScore], *, event_ts: datetime | None = None) -> int:
    if not scores:
        return 0
    now = utcnow()
    written = 0
    for item in scores:
        row = session.get(RawPostRow, item.raw_post_id)
        ts = to_utc(row.event_ts) if row is not None and row.event_ts is not None else to_utc(event_ts or now)
        session.add(
            SentimentRow(
                raw_post_id=item.raw_post_id,
                event_ts=ts,
                ingested_at=now,
                label=item.label,
                score=float(item.score),
                method=METHOD,
            )
        )
        if row is not None:
            raw = dict(row.raw_json) if isinstance(row.raw_json, dict) else {}
            raw["ai_score"] = float(item.score)
            raw["ai_credibility"] = float(item.credibility)
            raw["ai_label"] = item.label
            raw["ai_reason"] = item.reason
            raw["ai_method"] = METHOD
            # Blend host prior with AI credibility for downstream attention mass.
            prior = raw.get("source_weight")
            if prior is None:
                prior = source_weight(
                    feed_url=str(raw.get("feed_url") or "") or None,
                    article_url=row.url,
                )
            raw["source_weight"] = float(prior) * (0.25 + 0.95 * float(item.credibility))
            row.raw_json = raw
        written += 1
    session.flush()
    return written


def score_recent_posts_ai(
    session: Session,
    settings: Settings,
    *,
    as_of: datetime | None = None,
    http_post: HttpPostFn | None = None,
) -> dict[str, Any]:
    """Score unscored recent posts; no-op when AI is disabled or no API key."""
    endpoint = resolve_ai_endpoint(settings)
    if endpoint is None:
        return {"enabled": False, "scored": 0, "skipped": "disabled_or_no_api_key"}
    now = to_utc(as_of or utcnow())
    posts = select_posts_for_ai(
        session,
        as_of=now,
        lookback_seconds=int(settings.ai_sentiment.lookback_seconds),
        limit=int(settings.ai_sentiment.max_posts),
    )
    if not posts:
        return {"enabled": True, "scored": 0, "skipped": "none_pending"}
    scores = score_posts_with_llm(posts, settings, http_post=http_post)
    n = persist_ai_scores(session, scores, event_ts=now)
    return {
        "enabled": True,
        "scored": n,
        "requested": len(posts),
        "provider_model": endpoint[2],
    }


def ai_consensus_for_posts(
    session: Session, post_ids: list[int]
) -> tuple[float, int, float]:
    """Credibility-weighted mean of llm_v1 scores. Returns (net, scored_count, mean_cred)."""
    if not post_ids:
        return 0.0, 0, 0.0
    rows = list(
        session.scalars(
            select(SentimentRow).where(
                SentimentRow.raw_post_id.in_(post_ids),
                SentimentRow.method == METHOD,
            )
        ).all()
    )
    if not rows:
        return 0.0, 0, 0.0
    # Latest score wins if duplicates exist.
    by_id: dict[int, SentimentRow] = {}
    for row in rows:
        prev = by_id.get(int(row.raw_post_id))
        if prev is None or to_utc(row.ingested_at) >= to_utc(prev.ingested_at):
            by_id[int(row.raw_post_id)] = row
    posts = {
        int(p.id): p
        for p in session.scalars(select(RawPostRow).where(RawPostRow.id.in_(list(by_id)))).all()
    }
    num = 0.0
    den = 0.0
    cred_sum = 0.0
    for pid, sent in by_id.items():
        post = posts.get(pid)
        raw = post.raw_json if post is not None and isinstance(post.raw_json, dict) else {}
        cred = _clip_cred(raw.get("ai_credibility"), default=0.5)
        num += float(sent.score) * cred
        den += cred
        cred_sum += cred
    n = len(by_id)
    if den <= 0:
        return 0.0, n, 0.0
    return num / den, n, cred_sum / n
