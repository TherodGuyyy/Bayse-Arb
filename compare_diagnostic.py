"""
Diagnostic: fetches the event LIST (what the bot normally uses) and the
single-event DETAIL endpoint for the same specific event, side by side —
to check whether the detail endpoint carries more reliable/live prices
than the list endpoint does.

Set SEARCH_TITLE below to something distinctive from one of the events
showing a suspicious near-100% "arbitrage" (e.g. part of "Elon Musk" or
"Davido" or "GTA"), then run this via the temporary workflow.
"""

import json
import logging
import os

from bayse_client import BayseClient, get_field

logging.basicConfig(level=logging.INFO)

SEARCH_TITLE = os.getenv("SEARCH_TITLE", "Elon Musk")


def main():
    client = BayseClient()
    print(f"Searching for an event with '{SEARCH_TITLE}' in the title...\n")

    all_events = client.list_all_events()
    match = None
    for event in all_events:
        title = get_field(event, "title") or ""
        if SEARCH_TITLE.lower() in title.lower():
            match = event
            break

    if not match:
        print(f"No event found matching '{SEARCH_TITLE}' in this batch of {len(all_events)} events.")
        print("Try a different SEARCH_TITLE, or check the full list below:")
        for e in all_events[:30]:
            print(" -", get_field(e, "title"))
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
