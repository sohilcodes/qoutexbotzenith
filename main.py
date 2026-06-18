from fastapi import FastAPI
import asyncio

from bot import run_bot

app = FastAPI()

@app.on_event("startup")
async def startup():
    asyncio.create_task(run_bot())
    print("🤖 BOT STARTED")

@app.get("/")
async def root():
    return {
        "status": "running"
    }

@app.get("/health")
async def health():
    return {
        "ok": True
    }
