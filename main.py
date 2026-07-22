"""
Bayse internal-arbitrage scanner — entry point.

Usage:
    python main.py

Runs a REST polling loop (interval set by POLL_INTERVAL_SECONDS in config /
.env) that:
  1. Fetches all active prediction-market events from Bayse
  2. Filters to those resolving within MAX_DAYS_TO_RESOLUTION
  3. Checks each for single-market or combined-event arbitrage
  4. Sends a Telegram alert for anything above MIN_PROFIT_MARGIN,
     respecting ALERT_COOLDOWN_SECONDS per event so you're not spammed
     every poll cycle for the same standing opportunity.

Stop with Ctrl+C. Since this runs on your personal machine "on and off",
it only catches opportunities while it's actually running — nothing
persists between sessions except the in-memory cooldown tracker, which
resets each time you start it.
"""

import logging
import time
from datetime import datetime, timezone

import config
from bayse_client import BayseClient
from arbitrage import scan_event
from telegram_alerts import send_alert, send_status

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("main")

# event_id -> last alert timestamp (epoch seconds)
_last_alerted: dict[str, float] = {}

# Tracks whether the last scan pass successfully reached Bayse, so we only
# send one "lost connection" message and one "back online" message per
# outage — not a fresh message every single failed retry.
_connection_state = {"connected": True}


def _should_alert(event_id: str) -> bool:
    last = _last_alerted.get(event_id)
    if last is None:
        return True
    return (time.time() - last) >= config.ALERT_COOLDOWN_SECONDS


def run_once(client: BayseClient) -> tuple[bool, int]:
    """
    Run a single scan pass.
    Returns (success, alerts_sent). success=False means we couldn't even
    reach Bayse this pass.
    """
    try:
        events = client.list_all_events()
    except Exception as e:
        log.error("Failed to fetch events from Bayse: %s", e)
        # In continuous (always-running) mode, track connection state across
        # polls so we alert once per outage, not once per failed retry.
        # In RUN_ONCE mode (GitHub Actions) each invocation is a fresh
        # process, so this state doesn't carry over — we skip the Telegram
        # noise and instead exit non-zero, which makes GitHub Actions mark
        # the run as failed and (by default) email you about it.
        if not config.RUN_ONCE:
            if _connection_state["connected"]:
                send_status(
                    "⚠️ Bayse arb bot: lost connection to Bayse (or no internet). "
                    "Will keep retrying automatically — no action needed unless "
                    "this repeats for a long time."
                )
                _connection_state["connected"] = False
        return False, 0

    if not config.RUN_ONCE and not _connection_state["connected"]:
        send_status("✅ Bayse arb bot: back online, resuming normal scans.")
        _connection_state["connected"] = True

    log.info("Fetched %d events", len(events))
    alerts_sent = 0

    for raw_event in events:
        try:
            opp = scan_event(raw_event)
        except Exception as e:
            log.exception("Error scanning event: %s", e)
            continue

        if opp is None:
            continue

        if not _should_alert(opp.event_id):
            log.info("Suppressing repeat alert for %s (cooldown active)", opp.event_id)
            continue

        log.info(
            "Arbitrage found: %s [%s] margin=%.2f%%",
            opp.title, opp.kind, opp.profit_margin * 100,
        )
        if send_alert(opp):
            _last_alerted[opp.event_id] = time.time()
            alerts_sent += 1

    return True, alerts_sent


def main():
    if not config.BAYSE_PUBLIC_KEY:
        log.warning(
            "BAYSE_PUBLIC_KEY is not set — requests may fail. "
            "Set it in your .env once you have Bayse API access."
        )

    client = BayseClient()

    if config.RUN_ONCE:
        # GitHub Actions mode: do exactly one scan pass and exit.
        # The schedule (cron) triggers a fresh run of this whole script
        # repeatedly, so there's no loop to run here.
        log.info(
            "Running single scan pass (RUN_ONCE mode): "
            "max_days_to_resolution=%d, min_profit_margin=%.2f%%, fee_buffer=%.2f%%",
            config.MAX_DAYS_TO_RESOLUTION,
            config.MIN_PROFIT_MARGIN * 100,
            config.FEE_BUFFER * 100,
        )
        success, sent = run_once(client)
        if sent:
            log.info("Sent %d alert(s) this pass", sent)
        if not success:
            # Non-zero exit makes GitHub Actions mark this run as failed,
            # which triggers GitHub's built-in failure-notification email —
            # no extra Telegram code needed for that case.
            raise SystemExit(1)
        return

    # Continuous mode: personal machine, stays running and loops forever.
    log.info(
        "Starting scan loop: interval=%ds, max_days_to_resolution=%d, "
        "min_profit_margin=%.2f%%, fee_buffer=%.2f%%",
        config.POLL_INTERVAL_SECONDS,
        config.MAX_DAYS_TO_RESOLUTION,
        config.MIN_PROFIT_MARGIN * 100,
        config.FEE_BUFFER * 100,
    )
    send_status(
        f"✅ Bayse arb bot is live. Scanning every {config.POLL_INTERVAL_SECONDS}s, "
        f"markets resolving within {config.MAX_DAYS_TO_RESOLUTION} days, "
        f"min profit margin {config.MIN_PROFIT_MARGIN * 100:.1f}%."
    )

    while True:
        start = datetime.now(timezone.utc)
        success, sent = run_once(client)
        if sent:
            log.info("Sent %d alert(s) this pass", sent)
        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        sleep_for = max(0, config.POLL_INTERVAL_SECONDS - elapsed)
        time.sleep(sleep_for)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Stopped by user.")
