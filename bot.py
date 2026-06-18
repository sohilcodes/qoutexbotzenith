import asyncio
import os
import pandas as pd
import yfinance as yf
import httpx
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# CONFIG
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

QUOTEX_EMAIL = os.getenv("QUOTEX_EMAIL")
QUOTEX_PASSWORD = os.getenv("QUOTEX_PASSWORD")

TRADE_AMOUNT = float(os.getenv("DEFAULT_TRADE_AMOUNT", "1"))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))

DEMO_MODE = (
    os.getenv("DEMO_MODE", "true").lower()
    == "true"
)

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
            progress=False
        )

        if df.empty:
            return None

        return df

    except:
        return None


def rsi(close, period=14):

    delta = close.diff()

    gain = delta.where(
        delta > 0,
        0
    ).rolling(period).mean()

    loss = (
        -delta.where(
            delta < 0,
            0
        )
    ).rolling(period).mean()

    rs = gain / loss

    return (
        100
        -
        (
            100
            /
            (
                1
                +
                rs
            )
        )
    )


def ema(close, p):
    return close.ewm(
        span=p,
        adjust=False
    ).mean()


def generate_signal(yf_symbol, qx_symbol):

    df = get_market_data(
        yf_symbol
    )

    if df is None:
        return None

    close = df["Close"]

    if len(close) < 30:
        return None

    r = round(
        rsi(close).iloc[-1],
        2
    )

    e9 = ema(close, 9)

    e21 = ema(close, 21)

    call = (
        e9.iloc[-2]
        <
        e21.iloc[-2]
        and
        e9.iloc[-1]
        >
        e21.iloc[-1]
        and
        r < 70
    )

    put = (
        e9.iloc[-2]
        >
        e21.iloc[-2]
        and
        e9.iloc[-1]
        <
        e21.iloc[-1]
        and
        r > 30
    )

    if not call and not put:
        return None

    return {
        "asset": qx_symbol,
        "direction": (
            "CALL"
            if call
            else "PUT"
        ),
        "price": float(
            close.iloc[-1]
        ),
        "duration": 60,
        "rsi": r,
        "time": datetime.utcnow()
    }


async def telegram(text):

    if (
        not TELEGRAM_BOT_TOKEN
        or
        not TELEGRAM_CHAT_ID
    ):
        return

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}"
        f"/sendMessage"
    )

    async with httpx.AsyncClient() as c:

        await c.post(
            url,
            json={
                "chat_id":
                TELEGRAM_CHAT_ID,
                "text":
                text,
                "parse_mode":
                "HTML"
            }
        )


async def send_signal(signal):

    msg = f"""
🚀 <b>SIGNAL</b>

💹 {signal["asset"]}

📍 {signal["direction"]}

⏱ 1 Minute

📉 RSI:
{signal["rsi"]}

💰 ${TRADE_AMOUNT}
"""

    await telegram(msg)


async def execute_trade(signal):

    print(
        "TRADE:",
        signal["direction"]
    )


async def check_result(signal):

    await asyncio.sleep(
        signal["duration"]
    )

    symbol = next(
        x["yf"]
        for x in ASSETS
        if x["qx"]
        ==
        signal["asset"]
    )

    df = get_market_data(
        symbol
    )

    if df is None:
        return

    exit_price = float(
        df["Close"].iloc[-1]
    )

    entry = signal["price"]

    if (
        signal["direction"]
        ==
        "CALL"
    ):
        win = (
            exit_price
            >
            entry
        )
    else:
        win = (
            exit_price
            <
            entry
        )

    result = (
        "✅ WIN"
        if win
        else
        "❌ LOSS"
    )

    await telegram(
f"""
🎯 <b>RESULT</b>

💹 {signal["asset"]}

Entry:
{entry}

Exit:
{round(exit_price,5)}

{result}
"""
    )


async def run():

    print("BOT STARTED")

    while True:

        signal_found = False

        for asset in ASSETS:

            signal = generate_signal(
                asset["yf"],
                asset["qx"]
            )

            if signal:

                signal_found = True

                await send_signal(
                    signal
                )

                await execute_trade(
                    signal
                )

                await check_result(
                    signal
                )

                break

        if not signal_found:

            print(
                "NO SIGNAL"
            )

            await asyncio.sleep(
                CHECK_INTERVAL
            )


asyncio.run(
    run()
    )
