import httpx
from telegram import Update
from telegram.ext import ContextTypes

from arcus_bot.config import log
from arcus_bot.fills import fetch_fills, format_fill, parse_address, parse_indexes
from arcus_bot.store import store
from arcus_bot.watch import seed


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Arcus mainnet fill alerts.\n"
        "/add 0xaddress — watch subaccount 0\n"
        "/add 0xaddress 3 — one subaccount\n"
        "/add 0xaddress all — subaccounts 0-9\n"
        "/remove 0xaddress\n"
        "/list\n"
        "/fills 0xaddress\n"
        "Alerts start at the next fill. History is not replayed."
    )


async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    address = parse_address(args[0] if args else "")
    indexes = parse_indexes(args[1] if len(args) > 1 else None)
    if not address or indexes is None or len(args) > 2:
        await update.message.reply_text("Use /add 0xaddress [0-9|all]")
        return
    added = store.add(update.effective_chat.id, address, indexes)
    if not added:
        await update.message.reply_text("Already watching that, or this chat is at the 30 watch cap.")
        return
    client = context.application.bot_data["http"]
    for idx in added:
        try:
            await seed(client, address, idx)
        except httpx.HTTPError as exc:
            log.warning("seed %s %s", address, exc)
    context.application.bot_data["q"].put_nowait(1)
    labels = "all subaccounts" if added == list(range(10)) else ", ".join(map(str, added))
    await update.message.reply_text(f"Watching {address} ({labels}). Next fill will alert here.")


async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    address = parse_address(args[0] if args else "")
    if not address or len(args) > 2:
        await update.message.reply_text("Use /remove 0xaddress [0-9]")
        return
    idx = None
    if len(args) == 2:
        parsed = parse_indexes(args[1])
        if not parsed or parsed == list(range(10)):
            await update.message.reply_text("Use /remove 0xaddress [0-9]")
            return
        idx = parsed[0]
    n = store.remove(update.effective_chat.id, address, idx)
    context.application.bot_data["q"].put_nowait(1)
    await update.message.reply_text("Removed." if n else "That address is not on your list.")


async def list_watches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = store.list(update.effective_chat.id)
    if not rows:
        await update.message.reply_text("No addresses yet. /add 0xaddress")
        return
    lines = [f"{addr}  sub {idx}" for addr, idx in rows]
    await update.message.reply_text("\n".join(lines))


async def fills(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    address = parse_address(args[0] if args else "")
    indexes = parse_indexes(args[1] if len(args) > 1 else None)
    if not address or indexes is None or len(args) > 2 or len(indexes) != 1:
        await update.message.reply_text("Use /fills 0xaddress [0-9]")
        return
    idx = indexes[0]
    try:
        rows = await fetch_fills(context.application.bot_data["http"], address, idx, limit=5)
    except httpx.HTTPError:
        await update.message.reply_text("Arcus mainnet did not return fills. Try again.")
        return
    if not rows:
        await update.message.reply_text(f"No fills for {address} sub {idx}.")
        return
    text = "\n\n".join(format_fill(address, idx, row) for row in rows[:5])
    await update.message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)
