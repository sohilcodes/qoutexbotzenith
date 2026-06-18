from fastapi import FastAPI
import asyncio
import threading
from bot import run_bot

app = FastAPI(title="Quotex Auto Bot")

# Bot ko background mein chalao
def start_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_bot())

@app.on_event("startup")
async def startup_event():
    thread = threading.Thread(target=start_bot, daemon=True)
    thread.start()
    print("🤖 Bot thread started!")

@app.get("/")
async def root():
    return {"status": "✅ Quotex Auto Bot is running!", "mode": "RSI+EMA Strategy"}

@app.get("/health")
async def health():
    return {"status": "ok"}
