import httpx
from telegram import Update
from telegram.ext import ContextTypes

from arcus_bot.config import MAX_PER_CHAT, log
from arcus_bot.fills import (
    active_subaccounts,
    fetch_fills,
    merge_orders,
    parse_address,
    short,
    trade_card,
)
from arcus_bot.store import store
from arcus_bot.watch import seed

HELP = (
    "📈 Arcus trade alerts\n"
    "Get a message when a wallet opens, adds, reduces or closes a position.\n\n"
    "/add  watch a wallet\n"
    "/remove  stop watching one\n"
    "/list  your watchlist\n"
    "/trades  latest trades of a wallet\n"
    "/cancel  stop what I asked you"
)


def wallets(chat_id):
    book = {}
    for address, idx in store.list(chat_id):
        book.setdefault(address, []).append(idx)
    return list(book.items())


def numbered(chat_id):
    return "\n".join(
        f"{n}. {address}" for n, (address, _) in enumerate(wallets(chat_id), 1)
    )


def resolve(chat_id, text):
    text = text.strip()
    if text.isdigit():
        book = wallets(chat_id)
        if 1 <= int(text) <= len(book):
            return book[int(text) - 1][0]
        return None
    return parse_address(text)


def wake(context):
    context.application.bot_data["q"].put_nowait(1)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("ask", None)
    await update.message.reply_text(HELP)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("ask", None)
    await update.message.reply_text("Cancelled.")


async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["ask"] = "add"
    await update.message.reply_text("➕ Send the wallet address to watch.\n\n/cancel to stop")


async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not wallets(chat_id):
        await update.message.reply_text("📋 Your watchlist is empty.\n/add a wallet first.")
        return
    context.user_data["ask"] = "remove"
    await update.message.reply_text(
        f"🗑 Which wallet? Send its address or number.\n\n{numbered(chat_id)}\n\n/cancel to stop"
    )


async def trades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    context.user_data["ask"] = "trades"
    text = "📊 Send the wallet address."
    if wallets(chat_id):
        text = f"📊 Send a wallet address, or pick a number.\n\n{numbered(chat_id)}"
    await update.message.reply_text(f"{text}\n\n/cancel to stop")


async def list_watches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("ask", None)
    book = wallets(update.effective_chat.id)
    if not book:
        await update.message.reply_text("📋 Your watchlist is empty.\n/add a wallet to start.")
        return
    lines = []
    for n, (address, subs) in enumerate(book, 1):
        extra = f"  ·  {len(subs)} subaccounts" if len(subs) > 1 else ""
        lines.append(f"{n}. {address}{extra}")
    await update.message.reply_text("📋 Watchlist\n" + "\n".join(lines))


async def do_add(update, context, address):
    client = context.application.bot_data["http"]
    try:
        subs = await active_subaccounts(client, address)
    except httpx.HTTPError:
        await update.message.reply_text("Could not reach Arcus. Send the address again in a moment.")
        return False
    added = store.add(update.effective_chat.id, address, subs)
    if added is None:
        await update.message.reply_text(f"You are at the {MAX_PER_CHAT} wallet limit. /remove one first.")
        return True
    if not added:
        await update.message.reply_text("Already watching that wallet.")
        return True
    for idx in added:
        try:
            await seed(client, address, idx)
        except httpx.HTTPError as exc:
            log.warning("seed %s %s", address, exc)
    wake(context)
    await update.message.reply_text(
        f"✅ Watching\n{address}\n\nYou will get a message for every trade it makes."
    )
    return True


async def do_remove(update, context, address):
    removed = store.remove(update.effective_chat.id, address, None)
    wake(context)
    await update.message.reply_text("🗑 Removed." if removed else "That wallet is not on your list.")
    return True


async def do_trades(update, context, address):
    client = context.application.bot_data["http"]
    chat_id = update.effective_chat.id
    subs = dict(wallets(chat_id)).get(address)
    try:
        subs = subs or await active_subaccounts(client, address)
        found = []
        for idx in subs:
            rows = merge_orders(await fetch_fills(client, address, idx, limit=20))
            found += [(idx, row) for row in rows]
    except httpx.HTTPError:
        await update.message.reply_text("Could not load trades. Send the address again in a moment.")
        return False
    if not found:
        await update.message.reply_text("No trades yet for that wallet.")
        return True
    found.sort(key=lambda item: item[1]["createdAt"], reverse=True)
    cards = [await trade_card(client, address, idx, row) for idx, row in found[:3]]
    await update.message.reply_text(f"📊 Latest trades · {short(address)}\n\n" + "\n\n".join(cards))
    return True


ACTIONS = {"add": do_add, "remove": do_remove, "trades": do_trades}


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kind = context.user_data.get("ask")
    if not kind:
        await update.message.reply_text("Tap /help to see what I can do.")
        return
    address = resolve(update.effective_chat.id, update.message.text or "")
    if not address:
        await update.message.reply_text("That is not a wallet address. Send 0x and 40 characters.\n\n/cancel to stop")
        return
    if await ACTIONS[kind](update, context, address):
        context.user_data.pop("ask", None)
