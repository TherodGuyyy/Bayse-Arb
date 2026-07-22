"""
Configuration for the Bayse internal-arbitrage bot.

All values can be overridden via environment variables (e.g. in a .env file
loaded with `python-dotenv`, or exported in your shell). Nothing here is a
secret by itself, but BAYSE_PUBLIC_KEY / TELEGRAM_BOT_TOKEN obviously are —
keep your real .env out of version control.
"""

import os

try:
    from dotenv import load_dotenv
    load_dotenv()  # loads variables from a .env file in the working directory, if present
except ImportError:
    pass  # python-dotenv not installed — fine if you're exporting env vars another way

# ---------------------------------------------------------------------------
# Bayse API
# ---------------------------------------------------------------------------
BAYSE_BASE_URL = os.getenv("BAYSE_BASE_URL", "https://relay.bayse.markets")
BAYSE_WS_URL = os.getenv("BAYSE_WS_URL", "wss://socket.bayse.markets/ws/v1/markets")

# Read-only endpoints on Bayse only require the public key in a header
# (per their quickstart docs) — no HMAC signing needed for scanning/reading.
BAYSE_PUBLIC_KEY = os.getenv("BAYSE_PUBLIC_KEY", "")

# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ---------------------------------------------------------------------------
# Scan behavior
# ---------------------------------------------------------------------------
# How often to do a full REST reconciliation sweep of all events, in seconds.
# This is the reliable, confirmed-working path. WebSocket (faster, push-based)
# is layered on top once you've verified the live message format — see
# ws_client.py for notes.
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))

# Only scan markets/events resolving within this many days from now.
# You chose <=7 days (daily/weekly mix) so capital isn't tied up for months
# and settlement is fast.
MAX_DAYS_TO_RESOLUTION = int(os.getenv("MAX_DAYS_TO_RESOLUTION", "7"))

# Minimum guaranteed-profit margin (as a fraction, e.g. 0.01 = 1%) required
# before the bot alerts you. This is AFTER the fee buffer below is applied.
# Tune this once you've seen real numbers come through.
MIN_PROFIT_MARGIN = float(os.getenv("MIN_PROFIT_MARGIN", "0.01"))

# Fee buffer: since Bayse's exact per-market fee field is not confirmed from
# public docs alone, this is a safety cushion subtracted from the theoretical
# arb margin before comparing to MIN_PROFIT_MARGIN. If/when you confirm the
# real fee field name from a live API response, wire it into
# arbitrage.py::get_effective_fee() instead of relying solely on this buffer.
FEE_BUFFER = float(os.getenv("FEE_BUFFER", "0.02"))

# Avoid re-alerting on the same opportunity every single poll cycle.
# Cooldown in seconds before the same market/event can trigger another alert.
ALERT_COOLDOWN_SECONDS = int(os.getenv("ALERT_COOLDOWN_SECONDS", "600"))

# Bayse lists events paginated; how many to request per page.
EVENTS_PAGE_LIMIT = int(os.getenv("EVENTS_PAGE_LIMIT", "100"))

# When RUN_ONCE=true (set by the GitHub Actions workflow), the bot does a
# single scan pass and exits, instead of looping forever. GitHub Actions
# triggers a fresh run on a schedule, so the "loop" happens at the scheduling
# layer instead of inside the script.
RUN_ONCE = os.getenv("RUN_ONCE", "false").strip().lower() == "true"
