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
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != "0":
        raise RuntimeError(f"OKX error: {data}")
    # rows: [ts_ms, o, h, l, c, vol, volCcy, volCcyQuote, confirm]; newest first
    rows = [x for x in data["data"] if x[8] == "1"]   # closed candles only
    rows.sort(key=lambda x: int(x[0]))
    closes = [float(x[4]) for x in rows]
    close_ts = int(rows[-1][0]) / 1000 + BAR_SECONDS
    return "OKX BTC-USDT-SWAP", closes, close_ts


def from_kraken():
    now = int(time.time())
    r = requests.get(
        "https://futures.kraken.com/api/charts/v1/trade/PF_XBTUSD/1h",
        params={"from": now - 300 * BAR_SECONDS, "to": now},
        headers=HEADERS,
        timeout=20,
    )
    r.raise_for_status()
    rows = r.json()["candles"]                         # time in ms
    rows.sort(key=lambda x: x["time"])
    rows = [x for x in rows if x["time"] / 1000 + BAR_SECONDS <= now]
    closes = [float(x["close"]) for x in rows]
    close_ts = rows[-1]["time"] / 1000 + BAR_SECONDS
    return "Kraken PF_XBTUSD", closes, close_ts


def fetch_closes():
    errors = []
    for fn in (from_okx, from_kraken):
        try:
            source, closes, close_ts = fn()
            if len(closes) < 100:
                raise RuntimeError("too few candles")
            t = datetime.fromtimestamp(close_ts, tz=IST).strftime("%Y-%m-%d %H:%M")
            return source, closes, t
        except Exception as e:
            errors.append(f"{fn.__name__}: {e}")
    raise RuntimeError("All data sources failed: " + " | ".join(errors))


def ema(values, n):
    k = 2.0 / (n + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def compute_tsi(closes):
    pc = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    apc = [abs(x) for x in pc]
    num = ema(ema(pc, LONG), SHORT)
    den = ema(ema(apc, LONG), SHORT)
    tsi = [100 * a / b if b != 0 else 0.0 for a, b in zip(num, den)]
    sig = ema(tsi, SIGNAL)
    return tsi, sig


def detect_cross(tsi, sig):
    prev_diff = tsi[-2] - sig[-2]
    curr_diff = tsi[-1] - sig[-1]
    if prev_diff <= 0 < curr_diff:
        return "BULLISH"
    if prev_diff >= 0 > curr_diff:
        return "BEARISH"
    return None


def send_alert(text):
    print(text)
    if not (TG_TOKEN and TG_CHAT_ID):
        print("Telegram secrets missing")
        return
    r = requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        data={"chat_id": TG_CHAT_ID, "text": text},
        timeout=20,
    )
    if not r.json().get("ok"):
        print("Telegram error:", r.text)


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def main():
    if os.getenv("TEST_ALERT") == "1":
        source, closes, t = fetch_closes()     # also proves the data source works
        send_alert(f"Test OK - GitHub scanner connected. Data source: {source}, last close {t} IST")
        return
    source, closes, candle_time = fetch_closes()
    tsi, sig = compute_tsi(closes)
    cross = detect_cross(tsi, sig)
    state = load_state()
    if cross and state.get("last_alert") != candle_time:
        arrow = "🟢" if cross == "BULLISH" else "🔴"
        msg = (
            f"{arrow} [GitHub] BTC perp {LABEL} TSI({LONG},{SHORT},{SIGNAL}) {cross} crossover\n"
            f"Source: {source}\n"
            f"Price: {closes[-1]:,.2f}\n"
            f"TSI: {tsi[-1]:.2f} | Signal: {sig[-1]:.2f}\n"
            f"Candle close (IST): {candle_time}"
        )
        send_alert(msg)
        state["last_alert"] = candle_time
        save_state(state)
    else:
        print(f"[{candle_time} IST] {source} | no new crossover | TSI {tsi[-1]:.2f} vs signal {sig[-1]:.2f}")


if __name__ == "__main__":
    main()
