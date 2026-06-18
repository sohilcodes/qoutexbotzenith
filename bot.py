import asyncio
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

IST = ZoneInfo("Asia/Kolkata")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TRADE_AMOUNT = float(os.getenv("DEFAULT_TRADE_AMOUNT", "1"))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "20"))

ASSETS = [
    {"yf": "EURUSD=X", "qx": "EURUSD"},
    {"yf": "GBPUSD=X", "qx": "GBPUSD"},
    {"yf": "USDJPY=X", "qx": "USDJPY"},
]


def now_ist():
    return datetime.now(IST)


def next_minute_time(dt=None):
    if dt is None:
        dt = now_ist()
    return dt.replace(second=0, microsecond=0) + timedelta(minutes=1)


def fmt_time(dt=None):
    if dt is None:
        dt = now_ist()
    return dt.strftime("%d-%m-%Y %H:%M:%S") + " (UTC+05:30)"


def get_market_data(symbol):
    try:
        df = yf.download(
            symbol,
            period="1d",
            interval="1m",
            progress=False,
            auto_adjust=False,
            threads=False
        )

        if df is None or df.empty:
            print(f"DATA EMPTY: {symbol}")
            return None

        close = df["Close"]

        if hasattr(close, "squeeze"):
            close = close.squeeze()

        if close is None or len(close) == 0:
            print(f"CLOSE EMPTY: {symbol}")
            return None

        return close

    except Exception as e:
        print(f"DATA ERROR {symbol}: {e}")
        return None


def rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def ema(close, period):
    return close.ewm(span=period, adjust=False).mean()


def generate_signal(yf_symbol, qx_symbol):
    close = get_market_data(yf_symbol)

    if close is None:
        print(f"{qx_symbol}: no data")
        return None

    if len(close) < 30:
        print(f"{qx_symbol}: not enough candles -> {len(close)}")
        return None

    try:
        e9 = ema(close, 9)
        e21 = ema(close, 21)
        r = float(rsi(close).iloc[-1])
        last_price = float(close.iloc[-1])

        call = float(e9.iloc[-1]) > float(e21.iloc[-1]) and r < 70
        put = float(e9.iloc[-1]) < float(e21.iloc[-1]) and r > 30

        entry_time = next_minute_time()
        expiry_time = entry_time + timedelta(seconds=60)

        print(
            f"[{fmt_time()}] {qx_symbol} | candles={len(close)} | "
            f"price={last_price:.5f} | ema9={float(e9.iloc[-1]):.5f} | "
            f"ema21={float(e21.iloc[-1]):.5f} | rsi={r:.2f} | "
            f"call={call} | put={put} | entry={fmt_time(entry_time)}"
        )

        if not call and not put:
            return None

        return {
            "asset": qx_symbol,
            "direction": "CALL" if call else "PUT",
            "price": round(last_price, 5),
            "duration": 60,
            "rsi": round(r, 2),
            "signal_time": now_ist(),
            "entry_time": entry_time,
            "expiry_time": expiry_time
        }

    except Exception as e:
        print(f"SIGNAL ERROR {qx_symbol}: {e}")
        return None


async def telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TG SKIPPED: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                url,
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": text,
                    "parse_mode": "HTML"
                }
            )
            print("TG STATUS:", response.status_code)
            print("TG RESPONSE:", response.text)

    except Exception as e:
        print("TG ERROR:", e)


async def send_signal(signal):
    msg = f"""
<tg-emoji emoji-id="5350377396421797635">⭐️</tg-emoji> <b>SIGNAL</b>

<tg-emoji emoji-id="6217220428046273989">😬</tg-emoji> Asset: {signal["asset"]}
📍 Direction: {signal["direction"]}
📉 RSI: {signal["rsi"]}
💰 Amount: ${TRADE_AMOUNT}

🕒 Signal Time: {fmt_time(signal["signal_time"])}
⏭ Entry Time: {fmt_time(signal["entry_time"])}
⌛ Expiry Time: {fmt_time(signal["expiry_time"])}

💻 Coded By @Sohilcodes
"""
    await telegram(msg)


async def execute_trade(signal):
    print(
        f'[{fmt_time()}] TRADE {signal["asset"]} '
        f'{signal["direction"]} @ {signal["price"]} '
        f'ENTRY {fmt_time(signal["entry_time"])}'
    )


async def wait_until_entry(entry_time):
    while True:
        remaining = (entry_time - now_ist()).total_seconds()
        if remaining <= 0:
            break
        await asyncio.sleep(min(remaining, 1))


async def check_result(signal):
    await wait_until_entry(signal["entry_time"])
    await asyncio.sleep(signal["duration"])

    yf_symbol = next(
        x["yf"]
        for x in ASSETS
        if x["qx"] == signal["asset"]
    )

    close = get_market_data(yf_symbol)

    if close is None:
        print(f'[{fmt_time()}] RESULT SKIPPED: no data for {signal["asset"]}')
        return

    exit_price = round(float(close.iloc[-1]), 5)
    entry = signal["price"]

    if signal["direction"] == "CALL":
        win = exit_price > entry
    else:
        win = exit_price < entry

    msg = f"""
<tg-emoji emoji-id="5350377396421797635">⭐️</tg-emoji> <b>RESULT</b>

<tg-emoji emoji-id="6217220428046273989">😬</tg-emoji> Asset: {signal["asset"]}
📍 Direction: {signal["direction"]}

⏭ Entry Time: {fmt_time(signal["entry_time"])}
⌛ Result Time: {fmt_time()}

Entry: {entry}
Exit: {exit_price}

{"✅ WIN" if win else "❌ LOSS"}
"""
    await telegram(msg)


async def run_bot():
    print(f"BOT STARTED AT {fmt_time()}")

    await telegram("""
<tg-emoji emoji-id="5350377396421797635">⭐️</tg-emoji> Premium Star Test

<tg-emoji emoji-id="6217220428046273989">😬</tg-emoji> Premium Face Test
""")

    last_sent_key = None

    while True:
        try:
            print(f"[{fmt_time()}] CHECKING MARKET...")
            found = False

            for asset in ASSETS:
                signal = generate_signal(asset["yf"], asset["qx"])

                if signal:
                    signal_key = (
                        signal["asset"],
                        signal["direction"],
                        signal["entry_time"].strftime("%Y-%m-%d %H:%M")
                    )

                    if signal_key == last_sent_key:
                        print(f"[{fmt_time()}] DUPLICATE SIGNAL SKIPPED: {signal_key}")
                        continue

                    last_sent_key = signal_key
                    found = True

                    print(f"[{fmt_time()}] SIGNAL FOUND: {signal}")
                    await send_signal(signal)
                    await execute_trade(signal)
                    await check_result(signal)
                    break

            if not found:
                print(f"[{fmt_time()}] NO SIGNAL - sleeping {CHECK_INTERVAL}s")

            await asyncio.sleep(CHECK_INTERVAL)

        except Exception as e:
            print(f"[{fmt_time()}] BOT LOOP ERROR: {e}")
            await asyncio.sleep(10)
