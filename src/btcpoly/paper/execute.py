"""Paper execution: Kalshi + BTC + attention features → paper trade."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from btcpoly.attention.aggregate import build_attention_features
from btcpoly.config import Settings
from btcpoly.db.models import PaperTrade, Prediction
from btcpoly.db.session import session_scope
from btcpoly.edge.costs import apply_entry_costs
from btcpoly.ingestion.btc_market.spot import fetch_btc_return
from btcpoly.ingestion.kalshi.markets import fetch_market_odds, resolve_active_market
from btcpoly.ingestion.kalshi.trading_hours import evaluate_trading_gate
from btcpoly.models.baseline import MomentumScore, score_momentum
from btcpoly.models.momentum_attn import score_momentum_attn
from btcpoly.monitoring.feed import recent_headlines
from btcpoly.paper.bankroll import get_bankroll, max_trade_notional
from btcpoly.paper.rationale import build_trade_rationale
from btcpoly.paper.session import PaperSessionState, session_trade_block
from btcpoly.timeutil import utcnow


def _score(
    settings: Settings,
    *,
    ret: float,
    odds: Any,
    attn_z: float,
    sentiment_net: float = 0.0,
    ai_sentiment: float = 0.0,
    ai_scored: int = 0,
    ai_credibility: float = 1.0,
) -> MomentumScore:
    name = (settings.paper.model_name or "momentum_attn_v1").strip().lower()
    common = dict(
        ret=ret,
        p_up_market=odds.p_up_mid,
        up_ask=odds.up_ask,
        down_ask=odds.down_ask,
        spread=odds.spread_up,
        min_edge=settings.risk.min_edge,
        max_spread=settings.risk.max_spread,
        max_position_usd=settings.risk.max_position_usd,
        min_confidence=settings.risk.min_confidence,
        emergency_stop=settings.risk.emergency_stop,
    )
    if name in {"momentum_v0", "momentum"}:
        return score_momentum(**common)
    return score_momentum_attn(
        **common,
        attn_z=attn_z,
        sentiment_net=sentiment_net,
        ai_sentiment=ai_sentiment,
        ai_scored=ai_scored,
        ai_credibility=ai_credibility,
    )


def _block_buy(reason: str) -> tuple[str, str, str, float, float, float, float]:
    return "NO_TRADE", reason, "NONE", 0.0, 0.0, 0.0, 0.0


def execute_paper(
    settings: Settings,
    *,
    market_id: str | None = None,
    run_session: PaperSessionState | None = None,
) -> dict[str, Any]:
    now = utcnow()
    windows = settings.btc_market.windows_seconds or settings.btc_windows_seconds
    window = 60 if 60 in windows else int(windows[0] if windows else 60)

    try:
        spot = fetch_btc_return(settings, window_seconds=window)
        market = resolve_active_market(settings)
        odds = fetch_market_odds(settings, market)
    except Exception as exc:  # noqa: BLE001 — paper path should still return JSON
        with session_scope() as session:
            bankroll = get_bankroll(session, settings)
            row = PaperTrade(
                event_ts=now,
                ingested_at=now,
                market_id=market_id or "unavailable",
                side="NONE",
                size=0.0,
                entry_price=0.0,
                decision="NO_TRADE",
                reason=f"fetch_failed:{exc}",
            )
            session.add(row)
            session.flush()
            trade_id = row.id
            sources = [item.to_dict() for item in recent_headlines(session, settings, limit=10)]
        return {
            "mode": "paper",
            "decision": "NO_TRADE",
            "reason": f"fetch_failed:{exc}",
            "market_id": market_id or "unavailable",
            "trade_id": trade_id,
            "live_trading_armed": settings.live_trading_armed,
            "event_ts": now.isoformat(),
            "sources": sources,
            "bankroll": bankroll,
            "features": {},
            "trading_gate": {"ok": False, "reason": f"fetch_failed:{exc}"},
        }

    gate = evaluate_trading_gate(
        market.raw,
        now=now,
        order_min_size=settings.kalshi.order_min_size,
    )
    mid = market_id or odds.market_id
    with session_scope() as session:
        features = build_attention_features(
            session, as_of=now, market_id=mid, settings=settings
        )
        attn_z = float(features.get("attn_z_900") or 0.0)
        sentiment_net = float(features.get("sentiment_net_900") or 0.0)
        ai_sentiment = float(features.get("ai_sentiment_net_900") or 0.0)
        ai_scored = int(features.get("ai_sentiment_scored_900") or 0)
        ai_credibility = float(features.get("ai_credibility_mean_900") or 0.0)
        bankroll = get_bankroll(session, settings)
        score = _score(
            settings,
            ret=float(spot.ret or 0.0),
            odds=odds,
            attn_z=attn_z,
            sentiment_net=sentiment_net,
            ai_sentiment=ai_sentiment,
            ai_scored=ai_scored,
            ai_credibility=ai_credibility,
        )

        decision = score.decision
        reason = score.reason
        side = score.side
        entry_price = float(score.entry_price or 0.0)
        size = float(score.size or 0.0)
        fees = 0.0
        slippage = 0.0

        # Kalshi-aligned: no new bets unless the live window is accepting orders.
        if decision in {"BUY_UP", "BUY_DOWN"} and not gate.ok:
            decision, reason, side, entry_price, size, fees, slippage = _block_buy(gate.reason)

        if decision in {"BUY_UP", "BUY_DOWN"}:
            block = session_trade_block(
                settings,
                session=run_session,
                decision=decision,
                slug=str(odds.slug or mid),
                features=features,
            )
            if block:
                decision, reason, side, entry_price, size, fees, slippage = _block_buy(block)

        if decision in {"BUY_UP", "BUY_DOWN"}:
            open_n = int(
                session.scalar(
                    select(func.count())
                    .select_from(PaperTrade)
                    .where(
                        PaperTrade.decision.in_(("BUY_UP", "BUY_DOWN")),
                        PaperTrade.pnl.is_(None),
                    )
                )
                or 0
            )
            if open_n >= int(settings.risk.max_simultaneous_positions):
                decision, reason, side, entry_price, size, fees, slippage = _block_buy(
                    "max_open_positions"
                )

        if decision in {"BUY_UP", "BUY_DOWN"}:
            notional_cap = max_trade_notional(bankroll, settings)
            if notional_cap < 0.50:
                decision, reason, side, entry_price, size, fees, slippage = _block_buy(
                    "insufficient_cash"
                )
            else:
                costs = apply_entry_costs(
                    entry_price,
                    max_notional_usd=notional_cap,
                    fee_bps=settings.paper.fee_bps,
                    slippage_bps=settings.paper.slippage_bps,
                )
                total_cost = costs.notional + costs.fees
                min_shares = float(gate.order_min_size or market.order_min_size or 5.0)
                if total_cost > float(bankroll["cash"]) + 1e-9 or costs.size <= 0:
                    decision, reason, side, entry_price, size, fees, slippage = _block_buy(
                        "insufficient_cash"
                    )
                elif costs.size + 1e-9 < min_shares:
                    decision, reason, side, entry_price, size, fees, slippage = _block_buy(
                        "below_order_min_size"
                    )
                else:
                    entry_price = costs.entry_eff
                    size = costs.size
                    fees = costs.fees
                    slippage = costs.slippage

        explanation: dict[str, Any] = {
            "ret": score.ret,
            "edge": score.edge,
            "p_up_market": score.p_up_market,
            "spread": score.spread,
            "reason": reason,
            "slug": odds.slug,
            "odds_source": odds.source,
            "window_seconds": window,
            "attn_z_900": attn_z,
            "sentiment_net_900": sentiment_net,
            "ai_sentiment_net_900": ai_sentiment,
            "ai_sentiment_scored_900": ai_scored,
            "ai_credibility_mean_900": ai_credibility,
            "trading_gate": gate.to_dict(),
            "features": {
                "mention_count_300": features.get("mention_count_300"),
                "mention_count_900": features.get("mention_count_900"),
                "attn_z_300": features.get("attn_z_300"),
                "attn_z_900": features.get("attn_z_900"),
                "sentiment_net_300": features.get("sentiment_net_300"),
                "sentiment_net_900": features.get("sentiment_net_900"),
                "ai_sentiment_net_900": ai_sentiment,
                "ai_sentiment_scored_900": ai_scored,
                "ai_credibility_mean_900": ai_credibility,
            },
            "bankroll": {
                "cash": bankroll.get("cash"),
                "open_cost": bankroll.get("open_cost"),
                "settled_pnl": bankroll.get("settled_pnl"),
            },
            "fees": fees,
            "slippage": slippage,
        }
        prediction = Prediction(
            as_of_ts=now,
            ingested_at=now,
            market_id=mid,
            model_name=score.model_name,
            p_up=score.p_up,
            p_down=score.p_down,
            confidence=score.confidence,
            explanation=explanation,
        )
        session.add(prediction)
        row = PaperTrade(
            event_ts=now,
            ingested_at=now,
            market_id=mid,
            side=side,
            size=size,
            entry_price=entry_price,
            fees=fees,
            slippage=slippage,
            decision=decision,
            reason=reason,
        )
        session.add(row)
        session.flush()
        trade_id = row.id
        bankroll = get_bankroll(session, settings)
        sources = [item.to_dict() for item in recent_headlines(session, settings, limit=10)]
        if decision in {"BUY_UP", "BUY_DOWN"}:
            explanation["why"] = build_trade_rationale(
                {
                    "decision": decision,
                    "edge": score.edge,
                    "p_up_model": score.p_up,
                    "p_up_market": score.p_up_market,
                    "btc_ret": score.ret,
                    "slug": odds.slug,
                    "features": {
                        "attn_z_900": attn_z,
                        "sentiment_net_900": sentiment_net,
                        "ai_sentiment_net_900": ai_sentiment,
                        "ai_sentiment_scored_900": ai_scored,
                        "ai_credibility_mean_900": ai_credibility,
                        "mention_count_900": features.get("mention_count_900"),
                    },
                    "sources": sources,
                }
            )
            prediction.explanation = explanation

    out = {
        "mode": "paper",
        "decision": decision,
        "reason": reason,
        "market_id": mid,
        "side": side,
        "size": size,
        "entry_price": entry_price,
        "fees": fees,
        "slippage": slippage,
        "trade_id": trade_id,
        "model": score.model_name,
        "btc_price": spot.price,
        "btc_ret": score.ret,
        "btc_window_seconds": window,
        "slug": odds.slug,
        "p_up_model": score.p_up,
        "p_down_model": score.p_down,
        "p_up_market": score.p_up_market,
        "edge": score.edge,
        "spread": score.spread,
        "odds_source": odds.source,
        "confidence": score.confidence,
        "live_trading_armed": settings.live_trading_armed,
        "event_ts": now.isoformat(),
        "sources": sources,
        "bankroll": bankroll,
        "trading_gate": gate.to_dict(),
        "features": {
            "mention_count_300": features.get("mention_count_300"),
            "mention_count_900": features.get("mention_count_900"),
            "attn_z_300": features.get("attn_z_300"),
            "attn_z_900": features.get("attn_z_900"),
            "sentiment_net_300": features.get("sentiment_net_300"),
            "sentiment_net_900": features.get("sentiment_net_900"),
            "ai_sentiment_net_900": features.get("ai_sentiment_net_900"),
            "ai_sentiment_scored_900": features.get("ai_sentiment_scored_900"),
            "ai_credibility_mean_900": features.get("ai_credibility_mean_900"),
        },
    }
    if decision in {"BUY_UP", "BUY_DOWN"}:
        out["why"] = build_trade_rationale(out)
    return out
