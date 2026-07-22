"""
Sends arbitrage alerts to you via Telegram.

Setup (one-time):
1. Message @BotFather on Telegram, send /newbot, follow the prompts.
   You'll get a bot token like "123456:ABC-DEF...".
2. Message your new bot at least once (anything, e.g. "hi") so it's allowed
   to message you back.
3. Get your chat ID: visit
     https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   in a browser after step 2, and read the "chat":{"id": ...} value.
4. Put both into your .env as TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
"""

import logging
import requests

import config
from arbitrage import ArbOpportunity

log = logging.getLogger("telegram_alerts")


def _format_message(opp: ArbOpportunity) -> str:
    lines = [
        f"🔔 ARBITRAGE — {opp.kind.replace('_', ' ').title()}",
        f"Market: {opp.title}",
        f"Event ID: {opp.event_id}",
    ]
    if opp.resolution_date:
        lines.append(f"Resolves: {opp.resolution_date.strftime('%Y-%m-%d %H:%M UTC')}")

    lines.append("")
    for leg in opp.legs:
        lines.append(f"  {leg['label']} ({leg['side']}): {leg['ask']:.4f}")

    lines.append("")
    lines.append(f"Total cost to lock in payout of 1.00: {opp.total_cost:.4f}")
    lines.append(f"Fee buffer applied: {opp.fee_buffer_applied * 100:.2f}%")
    lines.append(f"Estimated guaranteed profit margin: {opp.profit_margin * 100:.2f}%")
    lines.append("")
    lines.append("⚠️ Verify live prices before executing — the market can move between scan and order.")

    return "\n".join(lines)


def send_status(message: str) -> bool:
    """
    Send a plain status message (not an arbitrage alert) — used for
    "bot is live", "lost connection", "back online" type notices.
    """
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        log.error("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — cannot send status. "
                   "Message was: %s", message)
        return False

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": config.TELEGRAM_CHAT_ID, "text": message}, timeout=10)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        log.error("Failed to send Telegram status message: %s", e)
        return False


def send_alert(opp: ArbOpportunity) -> bool:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        log.error("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — cannot send alert. "
                   "Printing to console instead:\n%s", _format_message(opp))
        return False

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": _format_message(opp),
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        log.error("Failed to send Telegram alert: %s", e)
        return False
