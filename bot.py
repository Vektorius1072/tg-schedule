import asyncio
import contextlib
import logging
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo
import requests


from aiohttp import ClientSession, ClientTimeout, web
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from api import format_tomorrow, format_week
from config import (
    APP_URL,
    BOT_TOKEN,
    DEFAULT_GROUP_ID,
    DEFAULT_GROUP_NAME,
    GROUP_CHAT_ID,
    GROUPS,
    PORT,
    SEND_HOUR,
    SEND_MINUTE,
    SELF_PING_INTERVAL_SECONDS,
    SELF_PING_START_DELAY_SECONDS,
    TIMEZONE,
    ADMIN_IDS,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

WEB_RUNNER_KEY = "web_runner"
SELF_PING_TASK_KEY = "self_ping_task"


def main_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("Расписание на завтра", callback_data="menu_tomorrow"),
            InlineKeyboardButton("Расписание на неделю", callback_data="menu_week"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def groups_keyboard(action: str) -> InlineKeyboardMarkup:
    keyboard = [[InlineKeyboardButton(name, callback_data=f"{action}:{gid}")] for name, gid in GROUPS.items()]
    keyboard.append([InlineKeyboardButton("Назад", callback_data="menu_back")])
    return InlineKeyboardMarkup(keyboard)


def _lookup_group_name(group_id: int) -> str | None:
    for name, gid in GROUPS.items():
        if gid == group_id:
            return name
    return None


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if update.message is None:
        return
    await update.message.reply_text(
        "Привет! Я бот расписания.\n\nВыбери, что хочешь узнать:",
        reply_markup=main_menu_keyboard(),
    )


async def cmd_tomorrow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if update.message is None:
        return

    if len(GROUPS) == 1:
        await _send_tomorrow(update.message, DEFAULT_GROUP_ID, DEFAULT_GROUP_NAME)
        return

    await update.message.reply_text("Выбери группу:", reply_markup=groups_keyboard("tomorrow"))


async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if update.message is None:
        return

    if len(GROUPS) == 1:
        await _send_week(update.message, DEFAULT_GROUP_ID, DEFAULT_GROUP_NAME)
        return

    await update.message.reply_text("Выбери группу:", reply_markup=groups_keyboard("week"))


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    query = update.callback_query
    if query is None:
        return

    await query.answer()
    data = query.data or ""

    if data == "menu_back":
        await query.edit_message_text("Выбери, что хочешь узнать:", reply_markup=main_menu_keyboard())
        return

    if data == "menu_tomorrow":
        if len(GROUPS) == 1:
            text = await _get_tomorrow_text(DEFAULT_GROUP_ID, DEFAULT_GROUP_NAME)
            await query.edit_message_text(text, parse_mode="HTML")
            return
        await query.edit_message_text("Выбери группу:", reply_markup=groups_keyboard("tomorrow"))
        return

    if data == "menu_week":
        if len(GROUPS) == 1:
            text = await _get_week_text(DEFAULT_GROUP_ID, DEFAULT_GROUP_NAME)
            await query.edit_message_text(text, parse_mode="HTML")
            return
        await query.edit_message_text("Выбери группу:", reply_markup=groups_keyboard("week"))
        return

    if data.startswith("tomorrow:") or data.startswith("week:"):
        action, _, raw_gid = data.partition(":")
        try:
            group_id = int(raw_gid)
        except ValueError:
            await query.edit_message_text("Некорректный идентификатор группы.")
            return

        group_name = _lookup_group_name(group_id)
        if group_name is None:
            await query.edit_message_text("Группа не найдена в настройках.")
            return

        if action == "tomorrow":
            text = await _get_tomorrow_text(group_id, group_name)
        else:
            text = await _get_week_text(group_id, group_name)
        await query.edit_message_text(text, parse_mode="HTML")


async def _get_tomorrow_text(group_id: int, group_name: str) -> str:
    try:
        del group_name
        return await format_tomorrow(group_id)
    except Exception:
        logger.exception("Failed to get tomorrow schedule")
        return "Не удалось получить расписание. Попробуй позже."


async def _get_week_text(group_id: int, group_name: str) -> str:
    try:
        return f"<b>Группа {escape(group_name)} - расписание на неделю</b>\n\n" + await format_week(group_id)
    except Exception:
        logger.exception("Failed to get week schedule")
        return "Не удалось получить расписание. Попробуй позже."


async def _send_tomorrow(message: Message, group_id: int, group_name: str):
    text = await _get_tomorrow_text(group_id, group_name)
    await message.reply_text(text, parse_mode="HTML")


async def _send_week(message: Message, group_id: int, group_name: str):
    text = await _get_week_text(group_id, group_name)
    await message.reply_text(text, parse_mode="HTML")


async def auto_send(app: Application):
    today = datetime.now(ZoneInfo(TIMEZONE))
    if today.weekday() == 5:
        logger.info("Saturday: autosend skipped")
        return

    logger.info("Autosend started")
    text = await _get_tomorrow_text(DEFAULT_GROUP_ID, DEFAULT_GROUP_NAME)
    await app.bot.send_message(chat_id=GROUP_CHAT_ID, text=text, parse_mode="HTML")


async def _healthcheck(_: web.Request) -> web.Response:
    return web.Response(text="Bot is alive!")


async def _self_ping_loop():
    if not APP_URL:
        logger.warning("APP_URL is not set. Self-ping disabled.")
        return

    await asyncio.sleep(SELF_PING_START_DELAY_SECONDS)
    timeout = ClientTimeout(total=15)

    while True:
        try:
            async with ClientSession(timeout=timeout) as session:
                async with session.get(APP_URL) as response:
                    logger.info("Self-ping sent. Status: %s", response.status)
        except Exception:
            logger.exception("Self-ping failed")
        await asyncio.sleep(SELF_PING_INTERVAL_SECONDS)


async def _post_init(app: Application):
    web_app = web.Application()
    web_app.router.add_get("/", _healthcheck)
    web_app.router.add_get("/health", _healthcheck)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    app.bot_data[WEB_RUNNER_KEY] = runner
    logger.info("Keepalive web server started on port %s", PORT)

    if APP_URL:
        self_ping_task = asyncio.create_task(_self_ping_loop(), name="self_ping")
        app.bot_data[SELF_PING_TASK_KEY] = self_ping_task
        logger.info("Self-ping enabled for %s every %s seconds", APP_URL, SELF_PING_INTERVAL_SECONDS)
    else:
        logger.warning("APP_URL is not set. Self-ping task was not started.")


async def _post_shutdown(app: Application):
    self_ping_task = app.bot_data.pop(SELF_PING_TASK_KEY, None)
    if self_ping_task is not None:
        self_ping_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self_ping_task

    runner = app.bot_data.pop(WEB_RUNNER_KEY, None)
    if runner is not None:
        await runner.cleanup()
        logger.info("Keepalive web server stopped")


### Пингуем апи, если не доступен оповещаем админов бота
async def ping_server(app: Application):
    try:
        resp = requests.get("https://api.thisishyum.ru/schedule_api/tyumen/groups/113/schedules?date=23-05-2026", timeout=5)
        logger.info(f"Ping OK: {resp.status_code}")
    except Exception as e:
        # Уведомляем всех админов
        for admin_id in ADMIN_IDS:
            try:
                await app.bot.send_message(
                    chat_id=admin_id,
                    text=f"⚠️ Сервер недоступен!\n\n`{e}`",
                    parse_mode="Markdown"
                )
            except Exception:
                pass  # если не смогли уведомить — не страшно

def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("tomorrow", cmd_tomorrow))
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(CallbackQueryHandler(handle_callback))

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        auto_send,
        CronTrigger(hour=SEND_HOUR, minute=SEND_MINUTE, timezone=TIMEZONE),
        args=[app],
    )
    scheduler.add_job(
    ping_server,
    "interval",
    seconds=10,
    args=[app],
    )
    scheduler.start()

    logger.info("Bot started")
    app.run_polling()




if __name__ == "__main__":
    main()
