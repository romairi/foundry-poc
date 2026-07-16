"""
telegram_bot.py

Telegram front-end for the SmartLoan Agent system (python-telegram-bot v20+).

Every regular text message is first triaged by the cheap/fast Fast Router
agent: greetings and generic FAQ get answered right away, while anything
loan-related is forwarded to the Orchestrator (which does the DB lookup,
policy RAG and DTI/LTV math). /start always goes straight to the
Orchestrator so it can personalize the greeting via the DB tool.

Each Telegram user gets their own Azure AI Foundry conversation thread with
the Orchestrator, kept in memory for the lifetime of the process, so it
remembers context across messages in the same chat. The Fast Router is
stateless (no thread reuse needed).

Run with:
    python telegram_bot.py
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Dict

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from agents_config import SmartLoanAgents, get_or_create_agents

load_dotenv()

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    level=logging.INFO,
)
# Quiet down the noisy HTTP libraries so our own trace prints stand out.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("azure").setLevel(logging.WARNING)
logger = logging.getLogger("smartloan.telegram_bot")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

WELCOME_PROMPT = (
    "The user just opened the chat with /start. Greet them warmly as the SmartLoan "
    "Assistant, try to recognize them via get_customer_financials, and ask what kind of "
    "loan (mortgage or consumer loan) they're interested in evaluating today."
)

# telegram_user_id -> Azure AI Foundry thread_id
_user_threads: Dict[int, str] = {}
_agents: "SmartLoanAgents | None" = None


def _banner(text: str) -> None:
    print("\n" + "─" * 60)
    print(text)
    print("─" * 60)


async def on_startup(application: Application) -> None:
    """Create/reuse the 3 SmartLoan agents before the bot starts polling."""
    global _agents
    _banner("🏦  SmartLoan Agent — starting up")
    print(f"[{datetime.now():%H:%M:%S}] Connecting to Azure AI Foundry...")

    # The Azure SDK calls below are synchronous/blocking; run them off the
    # event loop so they don't freeze the bot's startup coroutine.
    _agents = await asyncio.to_thread(get_or_create_agents)

    _banner("✅  All agents ready — bot is now listening on Telegram")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _handle_message(update, context, override_text=WELCOME_PROMPT)


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _handle_message(update, context)


async def _handle_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE, override_text: str | None = None
) -> None:
    if _agents is None:
        await update.message.reply_text(
            "⏳ The assistant is still starting up. Please try again in a few seconds."
        )
        return

    user = update.effective_user
    telegram_id = str(user.id)
    text = override_text or (update.message.text or "").strip()

    if not text:
        return

    print(f"\n👤 [{telegram_id}] {user.full_name}: {text}")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    try:
        # /start always goes straight to the Orchestrator (it needs the DB tool
        # to personalize the greeting). Regular messages are triaged first by
        # the cheap/fast Fast Router, which can answer small talk/FAQ directly
        # without ever invoking the Orchestrator pipeline.
        if not override_text:
            verdict = await asyncio.to_thread(_agents.route, text)
            if verdict["route"] == "direct" and verdict["reply"]:
                print(f"⚡ [{telegram_id}] Fast Router answered directly: {verdict['reply'][:300]}")
                await update.message.reply_text(verdict["reply"])
                return
            print(f"🧠 [{telegram_id}] Fast Router → routing to Orchestrator")

        # Give the model the Telegram ID explicitly so get_customer_financials can use it.
        prompt = text if override_text else f"[telegram_id={telegram_id}] {text}"
        thread_id = _user_threads.get(user.id)

        reply, thread_id = await asyncio.to_thread(_agents.ask, thread_id, prompt)
        _user_threads[user.id] = thread_id
        print(f"🤖 [{telegram_id}] SmartLoan Assistant: {reply[:300]}")
        await update.message.reply_text(reply)
    except Exception as exc:  # noqa: BLE001 - user-facing fallback for any agent/network error
        logger.exception("Error while handling message from %s", telegram_id)
        print(f"❌ [{telegram_id}] Error: {exc}")
        await update.message.reply_text(
            "⚠️ Sorry, something went wrong while processing your request. "
            "Please try again in a moment.\n\n"
            "⚠️ Извините, произошла ошибка при обработке запроса. Попробуйте ещё раз.\n\n"
            "⚠️ מצטערים, קרתה תקלה בעיבוד הבקשה. נסו שוב בעוד רגע."
        )


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. Add it to your .env file (get one from @BotFather)."
        )

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(on_startup)
        .build()
    )

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    print("🚀 Starting SmartLoan Telegram bot (Ctrl+C to stop)...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
