import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from config import (
    BOT_TOKEN, GROUP_CHAT_ID, GROUPS, DEFAULT_GROUP_ID,
    DEFAULT_GROUP_NAME, SEND_HOUR, SEND_MINUTE, TIMEZONE
)
from api import format_tomorrow, format_week

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ─── КЛАВИАТУРЫ ───────────────────────────────────────────────────────────────

def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню бота"""
    keyboard = [
        [
            InlineKeyboardButton("📅 Расписание на завтра", callback_data="menu_tomorrow"),
            InlineKeyboardButton("📆 Расписание на неделю", callback_data="menu_week"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def groups_keyboard(action: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора группы (легко расширяется через config.py)"""
    keyboard = []
    for name, gid in GROUPS.items():
        keyboard.append([
            InlineKeyboardButton(name, callback_data=f"{action}:{gid}")
        ])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="menu_back")])
    return InlineKeyboardMarkup(keyboard)


# ─── КОМАНДЫ ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я бот расписания ТКПСТ.\n\nВыбери что хочешь узнать:",
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown"
    )


async def cmd_tomorrow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /tomorrow — показать выбор группы для расписания на завтра"""
    # Если группа одна — сразу показываем расписание
    if len(GROUPS) == 1:
        await _send_tomorrow(update.message, DEFAULT_GROUP_ID, DEFAULT_GROUP_NAME)
    else:
        await update.message.reply_text(
            "Выбери группу:",
            reply_markup=groups_keyboard("tomorrow")
        )


async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /week — показать выбор группы для расписания на неделю"""
    if len(GROUPS) == 1:
        await _send_week(update.message, DEFAULT_GROUP_ID, DEFAULT_GROUP_NAME)
    else:
        await update.message.reply_text(
            "Выбери группу:",
            reply_markup=groups_keyboard("week")
        )


# ─── CALLBACK КНОПОК ──────────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu_back":
        await query.edit_message_text(
            "Выбери что хочешь узнать:",
            reply_markup=main_menu_keyboard()
        )

    elif data == "menu_tomorrow":
        if len(GROUPS) == 1:
            text = _get_tomorrow_text(DEFAULT_GROUP_ID, DEFAULT_GROUP_NAME)
            await query.edit_message_text(text, parse_mode="Markdown")
        else:
            await query.edit_message_text(
                "Выбери группу:",
                reply_markup=groups_keyboard("tomorrow")
            )

    elif data == "menu_week":
        if len(GROUPS) == 1:
            text = _get_week_text(DEFAULT_GROUP_ID, DEFAULT_GROUP_NAME)
            await query.edit_message_text(text, parse_mode="Markdown")
        else:
            await query.edit_message_text(
                "Выбери группу:",
                reply_markup=groups_keyboard("week")
            )

    elif data.startswith("tomorrow:"):
        gid = int(data.split(":")[1])
        name = next(k for k, v in GROUPS.items() if v == gid)
        text = _get_tomorrow_text(gid, name)
        await query.edit_message_text(text, parse_mode="Markdown")

    elif data.startswith("week:"):
        gid = int(data.split(":")[1])
        name = next(k for k, v in GROUPS.items() if v == gid)
        text = _get_week_text(gid, name)
        await query.edit_message_text(text, parse_mode="Markdown")


# ─── ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ──────────────────────────────────────────────────

def _get_tomorrow_text(group_id: int, group_name: str) -> str:
    try:
        return f"*Группа {group_name}*\n\n" + format_tomorrow(group_id)
    except Exception as e:
        logger.error(f"Ошибка получения расписания: {e}")
        return "❌ Не удалось получить расписание. Попробуй позже."


def _get_week_text(group_id: int, group_name: str) -> str:
    try:
        return f"*Группа {group_name} — расписание на неделю*\n\n" + format_week(group_id)
    except Exception as e:
        logger.error(f"Ошибка получения расписания: {e}")
        return "❌ Не удалось получить расписание. Попробуй позже."


async def _send_tomorrow(message, group_id: int, group_name: str):
    text = _get_tomorrow_text(group_id, group_name)
    await message.reply_text(text, parse_mode="Markdown")


async def _send_week(message, group_id: int, group_name: str):
    text = _get_week_text(group_id, group_name)
    await message.reply_text(text, parse_mode="Markdown")


# ─── АВТОРАССЫЛКА ─────────────────────────────────────────────────────────────

async def auto_send(app: Application):
    """Автоматически отправляет расписание на завтра в группу (кроме субботы)"""
    today = datetime.now(pytz.timezone(TIMEZONE))
    if today.weekday() == 5:  # суббота — не отправляем
        logger.info("Сегодня суббота, пропускаем авторассылку")
        return

    logger.info("Отправляю авторассылку расписания...")
    text = _get_tomorrow_text(DEFAULT_GROUP_ID, DEFAULT_GROUP_NAME)
    await app.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text=text,
        parse_mode="Markdown"
    )


# ─── ЗАПУСК ───────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("tomorrow", cmd_tomorrow))
    app.add_handler(CommandHandler("week", cmd_week))

    # Кнопки
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Планировщик авторассылки
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        auto_send,
        CronTrigger(hour=SEND_HOUR, minute=SEND_MINUTE, timezone=TIMEZONE),
        args=[app]
    )
    scheduler.start()

    logger.info("Бот запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()
