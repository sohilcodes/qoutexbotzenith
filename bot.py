import asyncio
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

IST = ZoneInfo("Asia/Kolkata")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TRADE_AMOUNT = float(os.getenv("DEFAULT_TRADE_AMOUNT", "1"))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))

ASSETS = [
    {"yf": "EURUSD=X", "qx": "EURUSD"},
    {"yf": "GBPUSD=X", "qx": "GBPUSD"},
    {"yf": "USDJPY=X", "qx": "USDJPY"},
]


def now_ist():
    return datetime.now(IST)


def fmt_time(dt=None):
    if dt is None:
        dt = now_ist()
    return dt.strftime("%d-%m-%Y %I:%M:%S %p") + " (UTC+05:30)"


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

        print(
            f"[{fmt_time()}] {qx_symbol} | candles={len(close)} | "
            f"price={last_price:.5f} | ema9={float(e9.iloc[-1]):.5f} | "
            f"ema21={float(e21.iloc[-1]):.5f} | rsi={r:.2f} | "
            f"call={call} | put={put}"
        )

        if not call and not put:
            return None

        return {
            "asset": qx_symbol,
            "direction": "CALL" if call else "PUT",
            "price": round(last_price, 5),
            "duration": 60,
            "rsi": round(r, 2),
            "time": now_ist()
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

    except Exception as e:
        print("TG ERROR:", e)


async def send_signal(signal):
    msg = f"""
🚀 <b>SIGNAL</b>

💹 Asset: {signal["asset"]}
📍 Direction: {signal["direction"]}
📉 RSI: {signal["rsi"]}
💰 Amount: ${TRADE_AMOUNT}
🕒 Time: {fmt_time(signal["time"])}

💻 Coded By @Sohilcodes
"""
    await telegram(msg)


async def execute_trade(signal):
    print(f'[{fmt_time()}] TRADE {signal["asset"]} {signal["direction"]} @ {signal["price"]}')


async def check_result(signal):
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
🎯 <b>RESULT</b>

💹 Asset: {signal["asset"]}
📍 Direction: {signal["direction"]}
🕒 Time: {fmt_time()}

Entry: {entry}
Exit: {exit_price}

{"✅ WIN" if win else "❌ LOSS"}
"""
    await telegram(msg)


async def run_bot():
    print(f"BOT STARTED AT {fmt_time()}")

    while True:
        try:
            print(f"[{fmt_time()}] CHECKING MARKET...")
            found = False

            for asset in ASSETS:
                signal = generate_signal(asset["yf"], asset["qx"])

                if signal:
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
