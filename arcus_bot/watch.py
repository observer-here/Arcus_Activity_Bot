import asyncio
import json

import httpx
import websockets
from telegram.error import TelegramError

from arcus_bot.config import ADDR, WS, log
from arcus_bot.fills import fetch_fills, merge_orders, short, trade_card
from arcus_bot.store import store


async def notify(bot, address, idx, text):
    for chat_id in store.chats(address, idx):
        try:
            await bot.send_message(chat_id, f"{text}\n👛 {short(address)}", disable_web_page_preview=True)
        except TelegramError as exc:
            log.warning("send failed chat=%s %s", chat_id, exc)


async def ingest(bot, client, address, idx, fills, alert):
    fresh = []
    for fill in fills:
        trade_id = str(fill.get("tradeId") or "")
        if not trade_id:
            continue
        if store.mark(address, idx, trade_id, fill.get("createdAt")):
            fresh.append(fill)
    if not alert or not fresh:
        return
    fresh = merge_orders(fresh)
    if len(fresh) > 12:
        skipped = len(fresh) - 8
        fresh = fresh[-8:]
        await notify(bot, address, idx, f"⏱ {skipped} earlier trades while the bot was offline")
    for fill in fresh:
        await notify(bot, address, idx, await trade_card(client, address, idx, fill))


async def seed(client, address, idx):
    if store.latest(address, idx):
        return
    fills = await fetch_fills(client, address, idx, limit=20)
    for fill in fills:
        trade_id = str(fill.get("tradeId") or "")
        if trade_id:
            store.mark(address, idx, trade_id, fill.get("createdAt"))
    if not fills:
        store.mark(address, idx, "seed", 0)


async def sync_subs(app, ws):
    client = app.bot_data["http"]
    live = app.bot_data["live"]
    want = {(addr, idx) for addr, idx in store.targets()}
    for addr, idx in sorted(want - live):
        last = store.latest(addr, idx)
        if last:
            try:
                fills = await fetch_fills(client, addr, idx, limit=100, from_us=last)
                await ingest(app.bot, client, addr, idx, fills, alert=True)
            except httpx.HTTPError as exc:
                log.warning("backfill %s %s", addr, exc)
        await ws.send(json.dumps({
            "type": "subscribe",
            "channel": "userFills",
            "id": addr,
            "accountIndex": idx,
            "snapshot": True,
            "nFills": 20,
        }))
        live.add((addr, idx))
    for addr, idx in sorted(live - want):
        await ws.send(json.dumps({
            "type": "unsubscribe",
            "channel": "userFills",
            "id": addr,
            "accountIndex": idx,
        }))
        live.discard((addr, idx))


async def on_message(app, raw):
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return
    if msg.get("channel") != "userFills":
        return
    if msg.get("type") not in ("subscribed", "channel_data"):
        return
    address = (msg.get("id") or "").lower()
    if not ADDR.fullmatch(address):
        return
    idx = int(msg.get("accountIndex") or 0)
    fills = (msg.get("contents") or {}).get("fills") or []
    await ingest(app.bot, app.bot_data["http"], address, idx, fills, alert=True)


async def run_ws(app):
    queue = app.bot_data["q"]
    while True:
        try:
            async with websockets.connect(WS, ping_interval=20, ping_timeout=20, max_size=4_000_000) as ws:
                log.info("mainnet socket connected")
                app.bot_data["live"].clear()
                await sync_subs(app, ws)
                incoming = asyncio.Queue()

                async def pump():
                    async for raw in ws:
                        await incoming.put(raw)

                pump_task = asyncio.create_task(pump())
                try:
                    while True:
                        recv = asyncio.create_task(incoming.get())
                        wake = asyncio.create_task(queue.get())
                        done, pending = await asyncio.wait(
                            {recv, wake, pump_task}, return_when=asyncio.FIRST_COMPLETED
                        )
                        for task in pending:
                            if task is not pump_task:
                                task.cancel()
                        cancelled = [task for task in pending if task is not pump_task]
                        if cancelled:
                            await asyncio.gather(*cancelled, return_exceptions=True)
                        if pump_task in done:
                            exc = pump_task.exception()
                            if exc:
                                raise exc
                            break
                        if wake in done:
                            while not queue.empty():
                                queue.get_nowait()
                            await sync_subs(app, ws)
                        if recv in done:
                            await on_message(app, recv.result())
                finally:
                    pump_task.cancel()
                    await asyncio.gather(pump_task, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("socket dropped: %s", exc)
            await asyncio.sleep(3)
