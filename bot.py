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

from api import (
    format_tomorrow,
    format_week,
    format_today,
    format_next_week,
    check_next_week_available,
)
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
    MAIN_ADMIN_ID,
    SCHEDULE_NOTIFY_ADMIN_ID,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

WEB_RUNNER_KEY = "web_runner"
SELF_PING_TASK_KEY = "self_ping_task"

# Флаг: было ли уже отправлено уведомление о расписании на следующую неделю
# Сбрасывается каждое воскресенье, проверяется с четверга
_next_week_notified: bool = False


# ─── КЛАВИАТУРЫ ───────────────────────────────────────────────────────────────

def main_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("Расписание на сегодня", callback_data="menu_today")
        ],
        [
            InlineKeyboardButton("Расписание на завтра", callback_data="menu_tomorrow"),
            InlineKeyboardButton("Расписание на неделю", callback_data="menu_week"),
        ],
        [
            InlineKeyboardButton("Расписание на след. неделю", callback_data="menu_next_week")
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def groups_keyboard(action: str) -> InlineKeyboardMarkup:
    keyboard = [[InlineKeyboardButton(name, callback_data=f"{action}:{gid}")] for name, gid in GROUPS.items()]
    keyboard.append([InlineKeyboardButton("Назад", callback_data="menu_back")])
    return InlineKeyboardMarkup(keyboard)


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Назад", callback_data="menu_back")]
    ])


def _lookup_group_name(group_id: int) -> str | None:
    for name, gid in GROUPS.items():
        if gid == group_id:
            return name
    return None


# ─── УВЕДОМЛЕНИЕ АДМИНОВ ОБ ОШИБКАХ ──────────────────────────────────────────

async def _notify_admins_error(app: Application, error: Exception, context_msg: str = "") -> None:
    """Отправляет описание ошибки главному админу"""
    try:
        text = f"⚠️ Ошибка: {context_msg}\n\n<code>{escape(str(error))}</code>"
        await app.bot.send_message(chat_id=MAIN_ADMIN_ID, text=text, parse_mode="HTML")
    except Exception:
        pass


# ─── КОМАНДЫ ──────────────────────────────────────────────────────────────────

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


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if update.message is None:
        return
    if len(GROUPS) == 1:
        await _send_today(update.message, DEFAULT_GROUP_ID, DEFAULT_GROUP_NAME)
        return
    await update.message.reply_text("Выбери группу:", reply_markup=groups_keyboard("today"))


async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if update.message is None:
        return
    if len(GROUPS) == 1:
        await _send_week(update.message, DEFAULT_GROUP_ID, DEFAULT_GROUP_NAME)
        return
    await update.message.reply_text("Выбери группу:", reply_markup=groups_keyboard("week"))


async def cmd_next_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if update.message is None:
        return
    if len(GROUPS) == 1:
        await _send_next_week(update.message, DEFAULT_GROUP_ID, DEFAULT_GROUP_NAME)
        return
    await update.message.reply_text("Выбери группу:", reply_markup=groups_keyboard("next_week"))


# ─── CALLBACK КНОПОК ──────────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query is None:
        return

    await query.answer()
    data = query.data or ""

    if data == "menu_back":
        await query.edit_message_text("Выбери, что хочешь узнать:", reply_markup=main_menu_keyboard())
        return

    if data == "menu_today":
        if len(GROUPS) == 1:
            text = await _get_today_text(DEFAULT_GROUP_ID, DEFAULT_GROUP_NAME, context.application)
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=back_keyboard())
            return
        await query.edit_message_text("Выбери группу:", reply_markup=groups_keyboard("today"))
        return

    if data == "menu_tomorrow":
        if len(GROUPS) == 1:
            text = await _get_tomorrow_text(DEFAULT_GROUP_ID, DEFAULT_GROUP_NAME, context.application)
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=back_keyboard())
            return
        await query.edit_message_text("Выбери группу:", reply_markup=groups_keyboard("tomorrow"))
        return

    if data == "menu_week":
        if len(GROUPS) == 1:
            text = await _get_week_text(DEFAULT_GROUP_ID, DEFAULT_GROUP_NAME, context.application)
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=back_keyboard())
            return
        await query.edit_message_text("Выбери группу:", reply_markup=groups_keyboard("week"))
        return

    if data == "menu_next_week":
        if len(GROUPS) == 1:
            text = await _get_next_week_text(DEFAULT_GROUP_ID, DEFAULT_GROUP_NAME, context.application)
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=back_keyboard())
            return
        await query.edit_message_text("Выбери группу:", reply_markup=groups_keyboard("next_week"))
        return

    if ":" in data:
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
            text = await _get_tomorrow_text(group_id, group_name, context.application)
        elif action == "today":
            text = await _get_today_text(group_id, group_name, context.application)
        elif action == "next_week":
            text = await _get_next_week_text(group_id, group_name, context.application)
        else:
            text = await _get_week_text(group_id, group_name, context.application)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=back_keyboard())


# ─── ПОЛУЧЕНИЕ ТЕКСТА ─────────────────────────────────────────────────────────

async def _get_tomorrow_text(group_id: int, group_name: str, app: Application | None = None) -> str:
    try:
        del group_name
        return await format_tomorrow(group_id)
    except Exception as e:
        logger.exception("Failed to get tomorrow schedule")
        if app:
            await _notify_admins_error(app, e, "расписание на завтра")
        return "Не удалось получить расписание. Попробуй позже."


async def _get_today_text(group_id: int, group_name: str, app: Application | None = None) -> str:
    try:
        del group_name
        return await format_today(group_id)
    except Exception as e:
        logger.exception("Failed to get today schedule")
        if app:
            await _notify_admins_error(app, e, "расписание на сегодня")
        return "Не удалось получить расписание. Попробуй позже."


async def _get_week_text(group_id: int, group_name: str, app: Application | None = None) -> str:
    try:
        return f"<b>Группа {escape(group_name)} — расписание на неделю</b>\n\n" + await format_week(group_id)
    except Exception as e:
        logger.exception("Failed to get week schedule")
        if app:
            await _notify_admins_error(app, e, "расписание на неделю")
        return "Не удалось получить расписание. Попробуй позже."


async def _get_next_week_text(group_id: int, group_name: str, app: Application | None = None) -> str:
    try:
        return f"<b>Группа {escape(group_name)} — расписание на следующую неделю</b>\n\n" + await format_next_week(group_id)
    except Exception as e:
        logger.exception("Failed to get next week schedule")
        if app:
            await _notify_admins_error(app, e, "расписание на следующую неделю")
        return "Не удалось получить расписание. Попробуй позже."


# ─── ОТПРАВКА ─────────────────────────────────────────────────────────────────

async def _send_tomorrow(message: Message, group_id: int, group_name: str):
    text = await _get_tomorrow_text(group_id, group_name)
    await message.reply_text(text, parse_mode="HTML")


async def _send_today(message: Message, group_id: int, group_name: str):
    text = await _get_today_text(group_id, group_name)
    await message.reply_text(text, parse_mode="HTML")


async def _send_week(message: Message, group_id: int, group_name: str):
    text = await _get_week_text(group_id, group_name)
    await message.reply_text(text, parse_mode="HTML")


async def _send_next_week(message: Message, group_id: int, group_name: str):
    text = await _get_next_week_text(group_id, group_name)
    await message.reply_text(text, parse_mode="HTML")


# ─── АВТОРАССЫЛКИ ─────────────────────────────────────────────────────────────

async def auto_send(app: Application):
    """Каждый день кроме субботы отправляет расписание на завтра в группу"""
    today = datetime.now(ZoneInfo(TIMEZONE))
    if today.weekday() == 5:
        logger.info("Saturday: autosend skipped")
        return
    logger.info("Autosend started")
    text = await _get_tomorrow_text(DEFAULT_GROUP_ID, DEFAULT_GROUP_NAME, app)
    for chat_id in GROUP_CHAT_IDS:
        await app.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")


async def auto_send_week(app: Application):
    """Каждый понедельник отправляет расписание на неделю в группу и закрепляет"""
    logger.info("Monday week autosend started")
    try:
        text = await _get_week_text(DEFAULT_GROUP_ID, DEFAULT_GROUP_NAME, app)
        for chat_id in GROUP_CHAT_IDS:
            message = await app.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML"
            )
            await app.bot.pin_chat_message(
                chat_id=chat_id,
                message_id=message.message_id,
                disable_notification=True,
            )
        logger.info("Week schedule sent and pinned")
    except Exception as e:
        logger.exception("Failed to send week schedule on Monday")
        await _notify_admins_error(app, e, "авторассылка недельного расписания")


async def check_next_week_schedule(app: Application):
    """
    Проверяет наличие расписания на следующую неделю (с четверга по воскресенье).
    Запускается в 9, 12, 15 и 18 часов.
    Если расписание появилось — отправляет его второму админу и прекращает проверки до след. недели.
    """
    global _next_week_notified

    if _next_week_notified:
        return

    today = datetime.now(ZoneInfo(TIMEZONE))
    # Проверяем только с четверга (3) по воскресенье (6)
    if today.weekday() < 3:
        return

    logger.info("Checking next week schedule availability...")
    available = await check_next_week_available(DEFAULT_GROUP_ID)

    if not available:
        logger.info("Next week schedule not available yet")
        return

    logger.info("Next week schedule found! Sending to admin...")
    try:
        text = await _get_next_week_text(DEFAULT_GROUP_ID, DEFAULT_GROUP_NAME, app)
        await app.bot.send_message(
            chat_id=SCHEDULE_NOTIFY_ADMIN_ID,
            text=f"📅 Появилось расписание на следующую неделю!\n\n{text}",
            parse_mode="HTML"
        )
        _next_week_notified = True
        logger.info("Next week schedule sent to admin, checks disabled until next week")
    except Exception as e:
        logger.exception("Failed to send next week schedule to admin")
        await _notify_admins_error(app, e, "отправка расписания на следующую неделю админу")


async def reset_next_week_flag(_app: Application):
    """Каждое воскресенье в 23:00 сбрасывает флаг — чтобы на следующей неделе проверки возобновились"""
    global _next_week_notified
    _next_week_notified = False
    logger.info("Next week notification flag reset")


# ─── KEEPALIVE ────────────────────────────────────────────────────────────────

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


# ─── ПИНГ API ─────────────────────────────────────────────────────────────────

async def ping_server(app: Application):
    """Пингует API, при недоступности уведомляет всех админов"""
    try:
        resp = requests.get("https://api.thisishyum.ru/schedule_api/tyumen/colleges", timeout=5)
        logger.info("Ping OK: %s", resp.status_code)
    except Exception as e:
        for admin_id in ADMIN_IDS:
            try:
                await app.bot.send_message(
                    chat_id=admin_id,
                    text=f"⚠️ Сервер недоступен!\n\n<code>{escape(str(e))}</code>",
                    parse_mode="HTML"
                )
            except Exception:
                pass


# ─── ЗАПУСК ───────────────────────────────────────────────────────────────────

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
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("next_week", cmd_next_week))
    app.add_handler(CallbackQueryHandler(handle_callback))

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    # Ежедневная рассылка расписания на завтра
    scheduler.add_job(
        auto_send,
        CronTrigger(hour=SEND_HOUR, minute=SEND_MINUTE, timezone=TIMEZONE),
        args=[app],
    )

    # Еженедельная рассылка расписания на неделю (понедельник)
    scheduler.add_job(
        auto_send_week,
        CronTrigger(day_of_week="mon", hour=SEND_HOUR, minute=SEND_MINUTE, timezone=TIMEZONE),
        args=[app],
    )

    # Проверка появления расписания на следующую неделю (чт–вс, 4 раза в день)
    scheduler.add_job(
        check_next_week_schedule,
        CronTrigger(day_of_week="thu,fri,sat,sun", hour="9,12,15,18", minute=0, timezone=TIMEZONE),
        args=[app],
    )

    # Сброс флага уведомления каждое воскресенье в 23:00
    scheduler.add_job(
        reset_next_week_flag,
        CronTrigger(day_of_week="sun", hour=23, minute=0, timezone=TIMEZONE),
        args=[app],
    )

    # Пинг API
    scheduler.add_job(
        ping_server,
        "interval",
        seconds=SELF_PING_INTERVAL_SECONDS,
        args=[app],
    )

    scheduler.start()

    logger.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
