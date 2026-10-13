"""Entry cost adjustments for paper trades (fees + slippage)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EntryCosts:
    ask: float
    entry_eff: float
    size: float
    notional: float
    fees: float
    slippage: float


def apply_entry_costs(
    ask: float,
    *,
    max_notional_usd: float,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> EntryCosts:
    """Worsen the ask by slippage_bps, size to notional, attach fee/slip dollars."""
    ask_f = float(ask)
    slip_mult = 1.0 + (float(slippage_bps) / 10_000.0)
    entry_eff = min(0.99, max(0.01, ask_f * slip_mult))
    size = max(0.0, float(max_notional_usd) / entry_eff) if entry_eff > 0 else 0.0
    notional = size * entry_eff
    # Slippage dollar cost vs raw ask fill.
    slippage = max(0.0, size * (entry_eff - ask_f))
    fees = notional * (float(fee_bps) / 10_000.0)
    return EntryCosts(
        ask=ask_f,
        entry_eff=entry_eff,
        size=size,
        notional=notional,
        fees=fees,
        slippage=slippage,
    )
