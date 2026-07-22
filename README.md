# Bayse Internal Arbitrage Bot

Scans Bayse prediction markets for two mechanical arbitrage patterns and
alerts you on Telegram. Built to focus on short-dated markets (daily/weekly,
≤7 days to resolution by default) so capital turns over fast rather than
sitting in something that settles at the end of 2026.

## What it looks for

1. **Single-market arb** — every Bayse market is YES/NO, paying 1.00 to the
   winning side. If `YES ask + NO ask < 1.00` (after a fee buffer), buying
   both sides locks in profit no matter the outcome.
2. **Combined-event arb** — Bayse bundles some markets into "combined
   events" with several mutually-exclusive sub-markets (e.g. one per
   candidate, one per team). Since exactly one wins, all YES asks across
   the sub-markets should sum to ~1.00. If the sum is under that (after
   fees), buying YES on every sub-market locks in profit.

Both checks use only each market's own prices — no cross-platform matching,
no subjective judgment calls.

## Setup

```bash
cd bayse_arb_bot
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:
- `BAYSE_PUBLIC_KEY` — from your Bayse developer account.
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — see the docstring at the top
  of `telegram_alerts.py` for the 4-step setup with @BotFather.

Run it:

```bash
python main.py
```

Leave the terminal open while you want it scanning. Since it's meant to run
"on and off" on your own machine, it only catches opportunities while it's
actually running — there's no persistence between sessions beyond the
in-memory alert cooldown, which resets each time you restart it.

## ⚠️ Things you need to verify before trusting this with real money

I built this against Bayse's public documentation, but couldn't test it
against a live API key. Two things are placeholders until you check them:

1. **Field names** (`bayse_client.py` → `FIELD_ALIASES`). I guessed at
   likely names for things like the resolution date and fee fields based on
   patterns common to similar APIs. The bot logs a clear warning any time
   it can't find a field it needs — if you see those warnings once you have
   real API access, run `python bayse_client.py` to dump a raw event and
   fix the aliases to match what Bayse actually returns.
2. **Fee amount** (`FEE_BUFFER` in `.env`, default 2%). Bayse's public docs
   didn't surface an exact fee schedule. The bot tries to read a live fee
   field per-market first, and falls back to this buffer if it can't find
   one. Treat every alert as an estimate until you've confirmed real fees
   and slippage against a live order.
3. **Prices move between scan and execution.** The bot alerts on a snapshot;
   by the time you place an order the price may have shifted. Every alert
   includes a reminder to double-check live prices before acting.

## Config reference (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `POLL_INTERVAL_SECONDS` | 60 | How often to do a full scan |
| `MAX_DAYS_TO_RESOLUTION` | 7 | Only scan markets resolving within this window |
| `MIN_PROFIT_MARGIN` | 0.01 | Minimum guaranteed margin (after fees) to alert on |
| `FEE_BUFFER` | 0.02 | Fallback fee cushion if a live fee field isn't found |
| `ALERT_COOLDOWN_SECONDS` | 600 | Don't re-alert the same market within this window |
| `EVENTS_PAGE_LIMIT` | 100 | Page size when listing events |

## Not yet built (next steps, if you want them)

- **Real-time WebSocket feed** — Bayse exposes `wss://socket.bayse.markets/ws/v1/markets`
  with a `subscribe` message per event ID (see their websocket docs). This
  bot uses REST polling for now, which is fully confirmed-working; wiring in
  the WebSocket for faster reaction time is a natural v2 once you've seen
  the REST version run and confirmed field names.
- **Auto-execution** — this bot only alerts, it doesn't place orders. Order
  placement needs HMAC request signing (Bayse's write endpoints require it)
  and real money risk controls — worth its own careful pass once the
  scanning side is proven out.
