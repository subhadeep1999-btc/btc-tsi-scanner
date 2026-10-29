"""
BTC perpetual TSI(25,13,13) crossover scanner for GitHub Actions
Data (tried in order, first that works wins):
  1. OKX    BTC-USDT-SWAP  (USDT perpetual, closest to Binance BTCUSDT perp)
  2. Kraken PF_XBTUSD      (USD perpetual)
No API key needed. Telegram token / chat id come from GitHub Secrets.
Runs once per invocation (the workflow schedules it).
"""
import os
import json
import time
from datetime import datetime, timezone, timedelta

import requests

LABEL = "1h"
BAR_SECONDS = 3600
LONG, SHORT, SIGNAL = 25, 13, 13
STATE_FILE = "state.json"

TG_TOKEN = os.getenv("TG_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")

IST = timezone(timedelta(hours=5, minutes=30))
HEADERS = {"User-Agent": "tsi-scanner/1.0"}


def from_okx():
    r = requests.get(
        "https://www.okx.com/api/v5/market/candles",
        params={"instId": "BTC-USDT-SWAP", "bar": "1H", "limit": "300"},
        headers=HEADERS,
        timeout=20,
