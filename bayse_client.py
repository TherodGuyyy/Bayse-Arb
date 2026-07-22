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
# Adjust/add to these once you've inspected a real response.
FIELD_ALIASES = {
    "resolution_date": ["resolutionDate", "resolveDate", "closeTime", "endDate", "expiry"],
    "yes_ask": ["yesAsk", "yesPrice", "yesAskPrice", "askYes"],
    "no_ask": ["noAsk", "noPrice", "noAskPrice", "askNo"],
    "fee": ["takerFeeBps", "takerFee", "feeBps", "fee"],
    "sub_markets": ["markets", "subMarkets", "outcomes"],
    "event_id": ["id", "eventId"],
    "title": ["title", "name", "question"],
}


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

    def list_all_events(self) -> list[dict]:
        """Page through all events."""
        all_events = []
        offset = 0
        while True:
            page = self.list_events(offset=offset)
            if not page:
                break
            all_events.extend(page)
            if len(page) < config.EVENTS_PAGE_LIMIT:
                break
            offset += config.EVENTS_PAGE_LIMIT
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
