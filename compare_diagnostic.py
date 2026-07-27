"""
Diagnostic: fetches the event LIST (what the bot normally uses) and the
single-event DETAIL endpoint for the same specific event, side by side —
to check whether the detail endpoint carries a resolution-date field the
list endpoint is missing.

Set SEARCH_ID below to (part of) a specific event ID you want to inspect —
e.g. one of the ones logged as "has no parseable resolution date".
"""

import json
import logging
import os

from bayse_client import BayseClient, get_field

logging.basicConfig(level=logging.INFO)

SEARCH_ID = os.getenv("SEARCH_ID", "bfb44828-bff5-4a47-98bb-b21c2ab947ae")


def main():
    client = BayseClient()
    print(f"Searching for an event with ID containing '{SEARCH_ID}'...\n")

    all_events = client.list_all_events()
    match = None
    for event in all_events:
        eid = str(get_field(event, "event_id") or "")
        if SEARCH_ID.lower() in eid.lower():
            match = event
            break

    if not match:
        print(f"No event found matching ID '{SEARCH_ID}' in this batch of {len(all_events)} events.")
        return

    event_id = get_field(match, "event_id")
    print("=" * 70)
    print("FROM THE LIST ENDPOINT (what the bot normally uses):")
    print("=" * 70)
    print(json.dumps(match, indent=2)[:2000])

    print()
    print("=" * 70)
    print(f"FROM THE SINGLE-EVENT DETAIL ENDPOINT (event_id={event_id}):")
    print("=" * 70)
    try:
        detail = client.get_event(event_id)
        print(json.dumps(detail, indent=2)[:2000])
    except Exception as e:
        print(f"Failed to fetch detail: {e}")


if __name__ == "__main__":
    main()
