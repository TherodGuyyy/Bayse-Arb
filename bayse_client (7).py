"""
Thin wrapper around Bayse's public read endpoints.

Per Bayse's quickstart docs: read endpoints only require your public key in
an `X-Public-Key` header — no HMAC signing needed (signing is only required
for write/order-placement endpoints, which this bot does not use, since it
only scans and alerts).

NOTE ON FIELD NAMES: the exact JSON shape of an event/market object could not
be verified without a live API key at build time. This client is written to
be defensive: it looks for a handful of plausible field name variants for
things like "resolution date" and "fee", and logs a warning the first time
it can't find a field it needs, so you find out immediately rather than
silently getting wrong numbers. Once you have real API access, run
`python bayse_client.py` directly (see bottom of this file) to dump a raw
event and confirm/adjust the field names in `FIELD_ALIASES` below.
"""

import logging
import requests
from typing import Any, Optional

import config

log = logging.getLogger("bayse_client")

# Plausible field name variants seen across similar prediction-market APIs.
#
# MAJOR CORRECTION (2026-07-27, from a real side-by-side comparison of the
# list endpoint vs the single-event detail endpoint): yesBuyPrice/
# noBuyPrice are NOT the live prices — they appear to be dead/placeholder
# fields that read exactly 0 regardless of the real market state. This is
# exactly why every arbitrage check using them produced false positives.
#
# The REAL live prices live inside each entry of the "markets" array, as
# "outcome1Price"/"outcome2Price", identified by "outcome1Label"/
# "outcome2Label" (e.g. "Yes"/"No") — NOT assumed to always be in that
# order. See get_yes_no_prices() below, which is now the correct way to
# read a sub-market's prices — the old yes_ask/no_ask aliases are kept
# only as a last-resort fallback in case some other event shape uses them
# for real.
FIELD_ALIASES = {
    "resolution_date": ["closingDate", "resolutionDate", "resolveDate", "closeTime", "endDate", "expiry"],
    "yes_ask": ["yesBuyPrice", "yesAsk", "yesPrice", "yesAskPrice", "askYes"],
    "no_ask": ["noBuyPrice", "noAsk", "noPrice", "noAskPrice", "askNo"],
    "fee": ["feePercentage", "takerFeeBps", "takerFee", "feeBps", "fee"],
    "sub_markets": ["markets", "subMarkets", "outcomes"],
    "event_id": ["id", "eventId"],
    "title": ["title", "name", "question"],
}


def get_yes_no_prices(sub_market: dict) -> tuple[Optional[float], Optional[float]]:
    """
    Reads the REAL live Yes/No prices from a sub-market object, using the
    confirmed real structure: outcome1Price/outcome2Price, identified by
    matching outcome1Label/outcome2Label against "yes"/"no" (case-
    insensitive) — NOT assumed to always be in outcome1/outcome2 order.
    Returns (yes_price, no_price), either of which may be None if this
    sub-market's shape doesn't match what we expect.
    """
    label1 = sub_market.get("outcome1Label")
    label2 = sub_market.get("outcome2Label")
    price1 = sub_market.get("outcome1Price")
    price2 = sub_market.get("outcome2Price")

    yes_price, no_price = None, None
    if isinstance(label1, str) and label1.strip().lower() == "yes":
        yes_price = price1
    elif isinstance(label1, str) and label1.strip().lower() == "no":
        no_price = price1

    if isinstance(label2, str) and label2.strip().lower() == "yes":
        yes_price = price2
    elif isinstance(label2, str) and label2.strip().lower() == "no":
        no_price = price2

    if yes_price is None or no_price is None:
        log.warning(
            "Sub-market didn't match expected Yes/No label pattern "
            "(outcome1Label=%r, outcome2Label=%r) — treating as unreadable "
            "rather than guessing.", label1, label2,
        )

    return yes_price, no_price


def _first_present(obj: dict, keys: list[str]) -> Optional[Any]:
    for k in keys:
        if k in obj and obj[k] is not None:
            return obj[k]
    return None


def get_field(obj: dict, logical_name: str) -> Optional[Any]:
    value = _first_present(obj, FIELD_ALIASES[logical_name])
    if value is None:
        log.warning(
            "Could not find field '%s' on object (tried %s). "
            "Inspect a live response and update FIELD_ALIASES in bayse_client.py.",
            logical_name, FIELD_ALIASES[logical_name],
        )
    return value


def get_field_with_source(obj: dict, logical_name: str) -> tuple[Optional[Any], Optional[str]]:
    """
    Same as get_field, but also returns WHICH specific alias key matched —
    needed for the fee field specifically, since "feePercentage" (a
    confirmed real Bayse field) means something different numerically than
    a generic "fee" or "feeBps" field would (percent vs basis points).
    """
    for key in FIELD_ALIASES[logical_name]:
        if key in obj and obj[key] is not None:
            return obj[key], key
    return None, None


class BayseClient:
    def __init__(self, public_key: str = None, base_url: str = None):
        self.public_key = public_key or config.BAYSE_PUBLIC_KEY
        self.base_url = (base_url or config.BAYSE_BASE_URL).rstrip("/")
        self.session = requests.Session()
        if self.public_key:
            self.session.headers.update({"X-Public-Key": self.public_key})

    def _get(self, path: str, params: dict = None) -> dict:
        url = f"{self.base_url}{path}"
        resp = self.session.get(url, params=params or {}, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def list_events(self, limit: int = None, offset: int = 0) -> list[dict]:
        """
        Fetch a page of prediction-market events.
        Endpoint per Bayse quickstart docs: GET /v1/pm/events
        """
        limit = limit or config.EVENTS_PAGE_LIMIT
        data = self._get("/v1/pm/events", params={"limit": limit, "offset": offset})
        # Defensive: some APIs wrap the list in {"data": [...]} or {"events": [...]}
        if isinstance(data, list):
            return data
        for key in ("data", "events", "results"):
            if key in data:
                return data[key]
        log.warning("Unexpected /v1/pm/events response shape: keys=%s", list(data.keys()))
        return []

    def list_all_events(self, max_pages: int = 50) -> list[dict]:
        """
        Page through all events.

        Hard-capped at max_pages (default 50, i.e. up to 5000 events at the
        default page size) so this can never loop forever if Bayse's real
        pagination behavior doesn't match what's assumed here (e.g. if it
        ever returns a full page repeatedly instead of eventually returning
        a shorter final page). If the cap is hit, we log a warning and
        return what we have rather than hanging indefinitely.
        """
        all_events = []
        offset = 0
        pages_fetched = 0
        seen_first_ids_per_page = set()

        while pages_fetched < max_pages:
            page = self.list_events(offset=offset)
            pages_fetched += 1

            if not page:
                break

            # Extra guard: if the "next" page is identical to a page we've
            # already seen (same first event's id), pagination likely isn't
            # advancing — stop instead of looping forever.
            first_id = get_field(page[0], "event_id")
            if first_id in seen_first_ids_per_page:
                log.warning(
                    "Pagination doesn't seem to be advancing (repeated page at "
                    "offset=%d) — stopping early. Check the offset/limit param "
                    "names against Bayse's real API.", offset,
                )
                break
            seen_first_ids_per_page.add(first_id)

            all_events.extend(page)
            if len(page) < config.EVENTS_PAGE_LIMIT:
                break
            offset += config.EVENTS_PAGE_LIMIT

        if pages_fetched >= max_pages:
            log.warning(
                "Hit the %d-page safety cap while fetching events — there may be "
                "more events than we fetched this pass. This is a safeguard, not "
                "expected behavior; worth checking Bayse's real pagination shape.",
                max_pages,
            )

        return all_events

    def get_event(self, event_id: str) -> dict:
        """Fetch full detail for a single event, including its sub-markets."""
        return self._get(f"/v1/pm/events/{event_id}")


if __name__ == "__main__":
    # Quick manual check: run `python bayse_client.py` after setting
    # BAYSE_PUBLIC_KEY to dump the first event and inspect its real shape.
    logging.basicConfig(level=logging.INFO)
    client = BayseClient()
    events = client.list_events(limit=1)
    import json
    print(json.dumps(events, indent=2))
