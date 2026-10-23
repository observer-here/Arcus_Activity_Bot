import asyncio
import logging
import os

import httpx
from telegram import BotCommand
from telegram.ext import Application, CommandHandler

from arcus_bot.config import load_env
from arcus_bot.handlers import add, list_watches, remove, start, trades
from arcus_bot.watch import run_ws


async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("add", "Watch a wallet"),
        BotCommand("remove", "Stop watching a wallet"),
        BotCommand("list", "Show your watchlist"),
        BotCommand("trades", "Latest trades for a wallet"),
        BotCommand("help", "How this bot works"),
    ])
    app.bot_data["q"] = asyncio.Queue()
    app.bot_data["http"] = httpx.AsyncClient()
    app.bot_data["live"] = set()
    app.bot_data["task"] = asyncio.create_task(run_ws(app))


async def post_shutdown(app: Application):
    app.bot_data["task"].cancel()
    await app.bot_data["http"].aclose()


def main():
    load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in the environment or .env")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("list", list_watches))
    app.add_handler(CommandHandler("trades", trades))
    app.add_handler(CommandHandler("fills", trades))
    app.run_polling()


if __name__ == "__main__":
    main()
