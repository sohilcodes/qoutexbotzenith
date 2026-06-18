import asyncio
import os
from datetime import datetime

import httpx
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TRADE_AMOUNT = float(os.getenv("DEFAULT_TRADE_AMOUNT", "1"))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))

ASSETS = [
    {"yf": "EURUSD=X", "qx": "EURUSD"},
    {"yf": "GBPUSD=X", "qx": "GBPUSD"},
    {"yf": "USDJPY=X", "qx": "USDJPY"},
]


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
            return None

        close = df["Close"]

        if hasattr(close, "squeeze"):
            close = close.squeeze()

        return close

    except Exception as e:
        print("DATA ERROR:", e)
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
        return None

    if len(close) < 30:
        return None

    try:
        e9 = ema(close, 9)
        e21 = ema(close, 21)
        r = float(rsi(close).iloc[-1])

        call = (
            float(e9.iloc[-2]) < float(e21.iloc[-2])
            and float(e9.iloc[-1]) > float(e21.iloc[-1])
            and r < 70
        )

        put = (
            float(e9.iloc[-2]) > float(e21.iloc[-2])
            and float(e9.iloc[-1]) < float(e21.iloc[-1])
            and r > 30
        )

        if not call and not put:
            return None

        return {
            "asset": qx_symbol,
            "direction": "CALL" if call else "PUT",
            "price": round(float(close.iloc[-1]), 5),
            "duration": 60,
            "rsi": round(r, 2),
            "time": datetime.utcnow()
        }

    except Exception as e:
        print("SIGNAL ERROR:", e)
        return None


async def telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                url,
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": text,
                    "parse_mode": "HTML"
                }
            )

    except Exception as e:
        print("TG ERROR:", e)


async def send_signal(signal):
    await telegram(
        f"""
🚀 <b>SIGNAL</b>

💹 {signal["asset"]}
📍 {signal["direction"]}

📉 RSI: {signal["rsi"]}

💰 ${TRADE_AMOUNT}

💻 Coded By @Sohilcodes
"""
    )


async def execute_trade(signal):
    print("TRADE", signal["direction"])


async def check_result(signal):
    await asyncio.sleep(60)

    close = get_market_data(
        next(
            x["yf"]
            for x in ASSETS
            if x["qx"] == signal["asset"]
        )
    )

    if close is None:
        return

    exit_price = round(float(close.iloc[-1]), 5)
    entry = signal["price"]

    if signal["direction"] == "CALL":
        win = exit_price > entry
    else:
        win = exit_price < entry

    await telegram(
        f"""
🎯 RESULT

💹 {signal["asset"]}

Entry: {entry}

Exit: {exit_price}

{"✅ WIN" if win else "❌ LOSS"}
"""
    )


async def run_bot():
    print("BOT STARTED")

    while True:
        found = False

        for asset in ASSETS:
            signal = generate_signal(asset["yf"], asset["qx"])

            if signal:
                found = True
                await send_signal(signal)
                await execute_trade(signal)
                await check_result(signal)
                break

        if not found:
            print("NO SIGNAL")
            await asyncio.sleep(CHECK_INTERVAL)
