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
from bayse_client import get_field, get_field_with_source, get_yes_no_prices

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
    Best-effort fee lookup, now using the CONFIRMED real Bayse field name
    (verified from a live event dump on 2026-07-27): "feePercentage" — and
    critically, that field means a literal percentage (a value of 10 means
    10%), NOT basis points. The previous version of this function guessed
    wrong here: it would have divided by 10,000 (treating 10 as 0.1%)
    instead of by 100 (the correct interpretation, 10%) — a 100x
    underestimate that could have made a genuinely unprofitable trade look
    like a guaranteed-profit arbitrage opportunity. Fixed now that we have
    real data to confirm against.

    Falls back to config.FEE_BUFFER if no fee field is found at all.
    """
    fee, matched_key = get_field_with_source(raw_event_or_market, "fee")
    if fee is None:
        return config.FEE_BUFFER

    fee = float(fee)

    if matched_key == "feePercentage":
        # Confirmed real field: value IS the percentage directly.
        fee = fee / 100.0
    elif fee > 1:
        # Fallback heuristic for any other/older field name this might
        # match — guess basis points if we don't know for sure.
        fee = fee / 10000.0

    return max(fee, config.FEE_BUFFER)


MIN_PLAUSIBLE_PRICE = 0.01  # a real YES/NO price this close to 0 or 1.00 is
                             # implausible for an actively-traded market —
                             # more likely a placeholder/stale value than a
                             # genuine price.


def _check_arbitrage_from_submarkets(raw_event: dict, sub_markets: list) -> Optional[ArbOpportunity]:
    """
    Unified arb check for BOTH simple markets and combined events — since
    the real Bayse structure confirmed on 2026-07-27 shows every event is
    just a "markets" list of one or more binary sub-markets, there's no
    real structural difference between them:
      - 1 sub-market  -> check that single market's Yes+No sum
      - 2+ sub-markets -> sum each sub-market's Yes price across all of them
    Each sub-market has its OWN fee (feePercentage) — the max fee found
    across all legs is used as a single conservative buffer for the whole
    basket (safer than averaging, since we don't know Bayse's exact
    per-leg fee mechanics for a multi-leg trade).
    """
    legs = []
    total_cost = 0.0
    fees = []
    event_title = get_field(raw_event, "title") or "Untitled"

    is_single = len(sub_markets) == 1

    for sub in sub_markets:
        if is_single:
            # For a single 2-outcome market, the SEMANTIC label doesn't
            # matter at all — we just need both prices to check if they
            # sum to less than 1. This works regardless of whether the
            # market labels its two outcomes "Yes"/"No", "Up"/"Down", or
            # anything else, since we're not trying to identify a specific
            # side, just checking the pair.
            price1 = sub.get("outcome1Price")
            price2 = sub.get("outcome2Price")
            if price1 is None or price2 is None:
                return None
            price1, price2 = float(price1), float(price2)
            if price1 < MIN_PLAUSIBLE_PRICE or price2 < MIN_PLAUSIBLE_PRICE:
                log.warning(
                    "Rejecting '%s' — price too close to 0 to be real "
                    "(price1=%.4f, price2=%.4f). Likely stale/placeholder data.",
                    event_title, price1, price2,
                )
                return None
            label1 = sub.get("outcome1Label") or "Outcome 1"
            label2 = sub.get("outcome2Label") or "Outcome 2"
            legs.append({"label": label1.upper(), "side": label1.upper(), "ask": price1})
            legs.append({"label": label2.upper(), "side": label2.upper(), "ask": price2})
            total_cost += price1 + price2
        else:
            # Combined multi-outcome event (e.g. an election): here we DO
            # need to consistently pick the same side across every
            # sub-market (the "this candidate wins" side), so label
            # matching against "Yes" specifically is required here.
            yes_price, _ = get_yes_no_prices(sub)
            if yes_price is None:
                return None  # incomplete/unrecognized data on this leg — skip rather than guess
            if yes_price < MIN_PLAUSIBLE_PRICE:
                log.warning(
                    "Rejecting combined event '%s' — a sub-market's YES price is "
                    "too close to 0 to be real (%.4f). Likely stale/placeholder data.",
                    event_title, yes_price,
                )
                return None
            legs.append({
                "label": get_field(sub, "title") or sub.get("outcome1Label") or "Outcome",
                "side": "YES",
                "ask": yes_price,
            })
            total_cost += yes_price

        fees.append(get_effective_fee(sub))

    fee = max(fees) if fees else config.FEE_BUFFER
    margin = 1.0 - total_cost - fee

    if margin >= config.MIN_PROFIT_MARGIN:
        return ArbOpportunity(
            kind="single_market" if is_single else "combined_event",
            title=event_title,
            event_id=str(get_field(raw_event, "event_id")),
            resolution_date=_parse_resolution_date(raw_event),
            legs=legs,
            total_cost=total_cost,
            fee_buffer_applied=fee,
            profit_margin=margin,
        )
    return None


def scan_event(raw_event: dict) -> Optional[ArbOpportunity]:
    """Entry point: checks one event for an arbitrage opportunity, using the
    real confirmed structure (a "markets" list of 1+ binary sub-markets)."""
    if not within_resolution_window(raw_event):
        return None

    sub_markets = get_field(raw_event, "sub_markets")
    if not sub_markets or not isinstance(sub_markets, list) or len(sub_markets) == 0:
        return None

    return _check_arbitrage_from_submarkets(raw_event, sub_markets)
