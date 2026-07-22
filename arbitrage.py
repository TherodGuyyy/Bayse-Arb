"""
Arbitrage detection for Bayse prediction markets.

Two mechanical, judgment-free patterns:

1. Single-market arb: every Bayse market has exactly two outcomes (YES/NO),
   and a winning share pays exactly 1.00. So if
       yes_ask + no_ask < 1.00 - fee_buffer
   buying both sides guarantees a profit no matter which way it resolves.

2. Combined-event arb: a "combined event" bundles several mutually exclusive
   sub-markets (e.g. one per candidate in an election). Since exactly one
   outcome wins, the YES asks across all sub-markets should sum to ~1.00.
   If
       sum(yes_ask for each sub-market) < 1.00 - fee_buffer
   buying YES on every sub-market locks in profit regardless of outcome.

Both checks only use each market's own displayed ask prices — no
cross-platform matching risk, no subjective judgment about whether two
markets "really" mean the same thing.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
import logging

from dateutil import parser as dateparser

import config
from bayse_client import get_field

log = logging.getLogger("arbitrage")


@dataclass
class ArbOpportunity:
    kind: str  # "single_market" or "combined_event"
    title: str
    event_id: str
    resolution_date: Optional[datetime]
    legs: list[dict]  # each leg: {"label": str, "side": "YES"/"NO", "ask": float}
    total_cost: float  # sum of asks needed to lock in the guaranteed payout of 1.00
    fee_buffer_applied: float
    profit_margin: float  # (1.00 - total_cost) as a fraction, after fee buffer


def _days_until(dt: Optional[datetime]) -> Optional[float]:
    if dt is None:
        return None
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt - now).total_seconds() / 86400.0


def _parse_resolution_date(raw_event: dict) -> Optional[datetime]:
    raw = get_field(raw_event, "resolution_date")
    if not raw:
        return None
    try:
        return dateparser.parse(raw)
    except (ValueError, TypeError):
        log.warning("Could not parse resolution date value: %r", raw)
        return None


def within_resolution_window(raw_event: dict, max_days: int = None) -> bool:
    """
    True if the event resolves within max_days from now.
    If we can't determine a resolution date at all, we exclude it by default
    (safer than accidentally alerting on a months-out market) and log a
    warning so you notice and can fix the field alias.
    """
    max_days = max_days if max_days is not None else config.MAX_DAYS_TO_RESOLUTION
    dt = _parse_resolution_date(raw_event)
    days = _days_until(dt)
    if days is None:
        log.warning(
            "Event %s has no parseable resolution date — excluding from scan. "
            "Verify the field alias in bayse_client.FIELD_ALIASES.",
            get_field(raw_event, "event_id"),
        )
        return False
    return 0 <= days <= max_days


def get_effective_fee(raw_event_or_market: dict) -> float:
    """
    Best-effort fee lookup. Falls back to config.FEE_BUFFER if the fee field
    isn't found on the object (see bayse_client.FIELD_ALIASES to fix this
    once you've confirmed the real field name from a live response).
    """
    fee = get_field(raw_event_or_market, "fee")
    if fee is None:
        return config.FEE_BUFFER
    # Guard against bps vs fraction confusion (e.g. "150" meaning 1.5%).
    fee = float(fee)
    if fee > 1:
        fee = fee / 10000.0  # assume bps
    return max(fee, config.FEE_BUFFER)


def check_single_market(raw_event: dict) -> Optional[ArbOpportunity]:
    """Check a plain (non-combined) event/market for YES+NO < 1 - fee."""
    yes_ask = get_field(raw_event, "yes_ask")
    no_ask = get_field(raw_event, "no_ask")
    if yes_ask is None or no_ask is None:
        return None

    yes_ask, no_ask = float(yes_ask), float(no_ask)
    fee = get_effective_fee(raw_event)
    total_cost = yes_ask + no_ask
    margin = 1.0 - total_cost - fee

    if margin >= config.MIN_PROFIT_MARGIN:
        return ArbOpportunity(
            kind="single_market",
            title=get_field(raw_event, "title") or "Untitled market",
            event_id=str(get_field(raw_event, "event_id")),
            resolution_date=_parse_resolution_date(raw_event),
            legs=[
                {"label": "YES", "side": "YES", "ask": yes_ask},
                {"label": "NO", "side": "NO", "ask": no_ask},
            ],
            total_cost=total_cost,
            fee_buffer_applied=fee,
            profit_margin=margin,
        )
    return None


def check_combined_event(raw_event: dict) -> Optional[ArbOpportunity]:
    """Check a combined event's sub-markets for sum(YES asks) < 1 - fee."""
    sub_markets = get_field(raw_event, "sub_markets")
    if not sub_markets or not isinstance(sub_markets, list) or len(sub_markets) < 2:
        return None

    legs = []
    total_cost = 0.0
    fee = get_effective_fee(raw_event)

    for sub in sub_markets:
        yes_ask = get_field(sub, "yes_ask")
        if yes_ask is None:
            return None  # incomplete data — skip rather than guess
        yes_ask = float(yes_ask)
        legs.append({
            "label": get_field(sub, "title") or "Outcome",
            "side": "YES",
            "ask": yes_ask,
        })
        total_cost += yes_ask

    margin = 1.0 - total_cost - fee

    if margin >= config.MIN_PROFIT_MARGIN:
        return ArbOpportunity(
            kind="combined_event",
            title=get_field(raw_event, "title") or "Untitled combined event",
            event_id=str(get_field(raw_event, "event_id")),
            resolution_date=_parse_resolution_date(raw_event),
            legs=legs,
            total_cost=total_cost,
            fee_buffer_applied=fee,
            profit_margin=margin,
        )
    return None


def scan_event(raw_event: dict) -> Optional[ArbOpportunity]:
    """Run the appropriate check depending on whether this is a combined event."""
    if not within_resolution_window(raw_event):
        return None

    sub_markets = get_field(raw_event, "sub_markets")
    if sub_markets and isinstance(sub_markets, list) and len(sub_markets) >= 2:
        return check_combined_event(raw_event)
    return check_single_market(raw_event)
