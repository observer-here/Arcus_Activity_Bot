import httpx
from telegram import ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes

from arcus_bot.config import log
from arcus_bot.fills import fetch_fills, parse_address, parse_indexes, trade_card
from arcus_bot.store import store
from arcus_bot.watch import seed

CLEAR = ReplyKeyboardRemove()


def wake(context):
    context.application.bot_data["q"].put_nowait(1)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📈 Arcus trade alerts\n\n"
        "/add 0xaddress\n"
        "Watch that wallet. Subaccount 0.\n\n"
        "/add 0xaddress all\n"
        "Watch every subaccount, 0 to 9.\n\n"
        "/remove 0xaddress\n"
        "/list\n"
        "/trades 0xaddress\n\n"
        "The next trade on a watched wallet shows up here.",
        reply_markup=CLEAR,
    )


async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    address = parse_address(args[0] if args else "")
    indexes = parse_indexes(args[1] if len(args) > 1 else None)
    if not address or indexes is None or len(args) > 2:
        await update.message.reply_text("Send /add 0xaddress\nOr /add 0xaddress all", reply_markup=CLEAR)
        return
    added = store.add(update.effective_chat.id, address, indexes)
    if not added:
        await update.message.reply_text("Already watching that wallet, or this chat is full (30).", reply_markup=CLEAR)
        return
    client = context.application.bot_data["http"]
    for idx in added:
        try:
            await seed(client, address, idx)
        except httpx.HTTPError as exc:
            log.warning("seed %s %s", address, exc)
    wake(context)
    if added == list(range(10)):
        where = "All subaccounts"
    else:
        where = "Subaccount " + ", ".join(map(str, added))
    await update.message.reply_text(f"✅ Watching {address}\n{where}\nNext trade alerts here.", reply_markup=CLEAR)


async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    address = parse_address(args[0] if args else "")
    if not address or len(args) > 2:
        await update.message.reply_text("Send /remove 0xaddress", reply_markup=CLEAR)
        return
    idx = None
    if len(args) == 2:
        parsed = parse_indexes(args[1])
        if not parsed or len(parsed) != 1:
            await update.message.reply_text("Send /remove 0xaddress 3 to drop one subaccount.", reply_markup=CLEAR)
            return
        idx = parsed[0]
    n = store.remove(update.effective_chat.id, address, idx)
    wake(context)
    await update.message.reply_text("🗑 Removed." if n else "That wallet is not on your list.", reply_markup=CLEAR)


async def list_watches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = store.list(update.effective_chat.id)
    if not rows:
        await update.message.reply_text("📋 Watchlist is empty.\nSend /add 0xaddress", reply_markup=CLEAR)
        return
    lines = [f"{addr}  · sub {idx}" for addr, idx in rows]
    await update.message.reply_text("📋 Watchlist\n" + "\n".join(lines), reply_markup=CLEAR)


async def trades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    address = parse_address(args[0] if args else "")
    indexes = parse_indexes(args[1] if len(args) > 1 else None)
    if not address or indexes is None or len(args) > 2 or len(indexes) != 1:
        await update.message.reply_text("Send /trades 0xaddress", reply_markup=CLEAR)
        return
    idx = indexes[0]
    client = context.application.bot_data["http"]
    try:
        rows = await fetch_fills(client, address, idx, limit=3)
    except httpx.HTTPError:
        await update.message.reply_text("Could not load trades. Try again.", reply_markup=CLEAR)
        return
    if not rows:
        await update.message.reply_text(f"No trades yet for {address}, subaccount {idx}.", reply_markup=CLEAR)
        return
    cards = [await trade_card(client, address, idx, row) for row in rows[:3]]
    await update.message.reply_text("\n\n".join(cards), reply_markup=CLEAR)
