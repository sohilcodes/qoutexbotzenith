import asyncio
import os
import pandas as pd
import numpy as np
import yfinance as yf
import httpx
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ===== CONFIG =====
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
QUOTEX_EMAIL = os.getenv("QUOTEX_EMAIL")
QUOTEX_PASSWORD = os.getenv("QUOTEX_PASSWORD")
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"
TRADE_AMOUNT = float(os.getenv("DEFAULT_TRADE_AMOUNT", "1"))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))  # seconds

# ===== ASSETS TO MONITOR =====
ASSETS = [
    {"yf": "EURUSD=X", "qx": "EURUSD"},
    {"yf": "GBPUSD=X", "qx": "GBPUSD"},
    {"yf": "USDJPY=X", "qx": "USDJPY"},
]

# ===== RSI CALCULATION =====
def calculate_rsi(prices: pd.Series, period: int = 14) -> float:
    delta = prices.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi.iloc[-1], 2)

# ===== EMA CALCULATION =====
def calculate_ema(prices: pd.Series, period: int) -> pd.Series:
    return prices.ewm(span=period, adjust=False).mean()

# ===== GET LIVE DATA =====
def get_market_data(symbol: str) -> pd.DataFrame | None:
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="1d", interval="1m")
        if df.empty or len(df) < 30:
            print(f"⚠️ Not enough data for {symbol}")
            return None
        return df
    except Exception as e:
        print(f"❌ Data fetch error for {symbol}: {e}")
        return None

# ===== SIGNAL GENERATOR =====
def generate_signal(symbol_yf: str, symbol_qx: str) -> dict | None:
    df = get_market_data(symbol_yf)
    if df is None:
        return None

    closes = df["Close"]
    current_price = round(closes.iloc[-1], 5)

    # Indicators calculate karo
    rsi = calculate_rsi(closes)
    ema9 = calculate_ema(closes, 9)
    ema21 = calculate_ema(closes, 21)

    ema9_now = ema9.iloc[-1]
    ema9_prev = ema9.iloc[-2]
    ema21_now = ema21.iloc[-1]
    ema21_prev = ema21.iloc[-2]

    # Signal conditions
    # CALL: EMA9 crosses above EMA21 + RSI not overbought
    call_signal = (ema9_prev < ema21_prev) and (ema9_now > ema21_now) and (rsi < 70)

    # PUT: EMA9 crosses below EMA21 + RSI not oversold
    put_signal = (ema9_prev > ema21_prev) and (ema9_now < ema21_now) and (rsi > 30)

    if not call_signal and not put_signal:
        return None

    direction = "CALL" if call_signal else "PUT"

    # Confidence level
    if call_signal and rsi < 40:
        confidence = "High"
    elif put_signal and rsi > 60:
        confidence = "High"
    else:
        confidence = "Medium"

    return {
        "asset": symbol_qx,
        "direction": direction,
        "duration": 60,
        "amount": TRADE_AMOUNT,
        "strategy": "RSI+EMA Crossover",
        "confidence": confidence,
        "price": str(current_price),
        "rsi": rsi,
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
    }

# ===== TELEGRAM ALERT =====
async def send_telegram_alert(signal: dict):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram credentials missing")
        return

    emoji = "🟢" if signal["direction"] == "CALL" else "🔴"
    direction_label = "📈 CALL (UP)" if signal["direction"] == "CALL" else "📉 PUT (DOWN)"
    confidence_emoji = "🔥" if signal["confidence"] == "High" else "⚡"

    message = f"""
{emoji} <b>QUOTEX AUTO SIGNAL</b> {emoji}
━━━━━━━━━━━━━━━━━━━
💹 <b>Asset:</b> {signal['asset']}
{direction_label}
⏱ <b>Duration:</b> 1 Minute
💰 <b>Amount:</b> ${signal['amount']}
{confidence_emoji} <b>Confidence:</b> {signal['confidence']}
📊 <b>Strategy:</b> {signal['strategy']}
📉 <b>RSI:</b> {signal['rsi']}
💲 <b>Price:</b> {signal['price']}
🕐 <b>Time:</b> {signal['timestamp']}
━━━━━━━━━━━━━━━━━━━
⚡ Auto-trading on Quotex...
⚠️ <i>Trade at your own risk</i>
"""

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML"
            }, timeout=10)
            if resp.status_code == 200:
                print(f"✅ Telegram alert sent!")
            else:
                print(f"❌ Telegram error: {resp.text}")
    except Exception as e:
        print(f"❌ Telegram failed: {e}")

# ===== QUOTEX TRADE =====
async def execute_trade(signal: dict):
    if not QUOTEX_EMAIL or not QUOTEX_PASSWORD:
        print("⚠️ Quotex credentials missing, skipping trade")
        return

    try:
        import websockets
        import json

        WS_URL = "wss://ws2.qxbroker.com/socket.io/?EIO=3&transport=websocket"

        # Login karo
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://qxbroker.com/api/v1/login",
                json={"email": QUOTEX_EMAIL, "password": QUOTEX_PASSWORD},
                headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
            )
            if resp.status_code != 200:
                print(f"❌ Quotex login failed: {resp.status_code}")
                return
            data = resp.json()
            token = data.get("token") or data.get("data", {}).get("token")
            if not token:
                print("❌ No token received")
                return

        # Trade place karo
        async with websockets.connect(WS_URL, extra_headers={"Authorization": f"Bearer {token}"}) as ws:
            await ws.send(json.dumps({"action": "authenticate", "token": token}))
            await asyncio.sleep(1)

            account_type = "practice" if DEMO_MODE else "real"
            await ws.send(json.dumps({
                "action": "buy",
                "asset": signal["asset"],
                "direction": signal["direction"].lower(),
                "duration": signal["duration"],
                "amount": signal["amount"],
                "account_type": account_type
            }))
            print(f"✅ Trade placed: {signal['direction']} {signal['asset']} ${signal['amount']} [{account_type}]")

    except Exception as e:
        print(f"❌ Trade error: {e}")

# ===== MAIN LOOP =====
async def run_bot():
    print("🤖 Quotex Auto Bot started!")
    print(f"📊 Monitoring: {[a['qx'] for a in ASSETS]}")
    print(f"⏱ Check interval: {CHECK_INTERVAL}s")
    print(f"🎮 Mode: {'DEMO' if DEMO_MODE else 'REAL'}")
    print("━" * 40)

    while True:
        print(f"\n🔍 Scanning signals... [{datetime.utcnow().strftime('%H:%M:%S')}]")

        for asset in ASSETS:
            try:
                signal = generate_signal(asset["yf"], asset["qx"])
                if signal:
                    print(f"📡 Signal found: {signal['direction']} {signal['asset']} (RSI: {signal['rsi']})")
                    await asyncio.gather(
                        send_telegram_alert(signal),
                        execute_trade(signal)
                    )
                else:
                    print(f"⏳ No signal for {asset['qx']} yet...")
            except Exception as e:
                print(f"❌ Error processing {asset['qx']}: {e}")

            await asyncio.sleep(2)  # assets ke beech gap

        print(f"⏰ Next scan in {CHECK_INTERVAL}s...")
        await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    asyncio.run(run_bot())
