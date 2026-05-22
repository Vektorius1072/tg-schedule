# tg-schedule

Telegram bot for university schedule:
- `/tomorrow` - lessons for tomorrow
- `/week` - lessons for the current week (Monday-Saturday)
- daily autosend to group chat

## Requirements

- Python 3.10+
- Telegram bot token
- Group chat ID for autosend

## Install

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Environment variables

Required:
- `BOT_TOKEN`
- `GROUP_CHAT_ID`

Optional:
- `API_BASE_URL` (default: `https://api.thisishyum.ru/schedule_api/tyumen`)
- `GROUPS_JSON` (default: `{"IS-25-3S":113}`)
- `DEFAULT_GROUP_ID` (default: first value from `GROUPS_JSON`)
- `DEFAULT_GROUP_NAME` (default: resolved from `DEFAULT_GROUP_ID`)
- `TIMEZONE` (default: `Europe/Moscow`)
- `SEND_HOUR` (default: `20`)
- `SEND_MINUTE` (default: `0`)
- `PORT` (default: `8080`, for keepalive web server)
- `APP_URL` (for self-ping, e.g. `https://my-bot.onrender.com`)
- `SELF_PING_INTERVAL_SECONDS` (default: `600`)
- `SELF_PING_START_DELAY_SECONDS` (default: `60`)

Example (`PowerShell`):

```powershell
$env:BOT_TOKEN="123456:token"
$env:GROUP_CHAT_ID="-1001234567890"
$env:GROUPS_JSON='{"IS-25-3S":113,"IS-25-4S":114}'
$env:DEFAULT_GROUP_ID="113"
$env:APP_URL="https://my-bot.onrender.com"
```

## Run

```bash
python bot.py
```

## Notes

- Bot uses async HTTP client (`httpx`) to avoid blocking Telegram event loop.
- Message formatting uses HTML and escapes dynamic fields from API.
- All date calculations use configured `TIMEZONE` consistently.
- Keepalive web server listens on `0.0.0.0:$PORT` with endpoints `/` and `/health`.
- If `APP_URL` is set, bot sends self-ping requests periodically to avoid sleep on free web hosting.

## Tests

```bash
python -m unittest discover -s tests -v
```
