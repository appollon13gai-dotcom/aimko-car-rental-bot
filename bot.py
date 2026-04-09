#!/usr/bin/env python3
"""
Telegram Bot for Car Rental Booking
Сайт: https://1aimko-tech-solutions-sl.hqrentals.eu
Автор: El Patrón
"""

import os
import logging
import asyncio
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)
from booking import CarRentalBooking

# Логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger(__name__)

# ─── Состояния диалога ─────────────────────────────────────────────────────────
(
    PICKUP_LOCATION,
    RETURN_LOCATION,
    PICKUP_DATE,
    PICKUP_TIME,
    RETURN_DATE,
    RETURN_TIME,
    SELECT_CAR,
    FIRST_NAME,
    LAST_NAME,
    EMAIL,
    PHONE,
    CONFIRM_BOOKING,
) = range(12)

# ─── Список локаций ────────────────────────────────────────────────────────────
LOCATIONS = [
    "Aeropuerto Barcelona",
    "Aeropuerto de Girona",
    "Badalona",
    "Barcelona Sants",
    "Blanes",
    "Calella",
    "El Masnou",
    "Empuriabrava",
    "Lloret de Mar",
    "L'Escala",
    "Malgrat de Mar",
    "Mataró",
    "Palamos",
    "Pineda de Mar",
    "Platja d'Aro",
    "Premiá de Mar",
    "Roses",
    "Sant Antoni de Calonge",
    "Sant Feliu de Guixols",
    "S'Agaro",
    "Tossa de Mar",
]

BRAND_UUID = "9dyo3zcw-nkwh-dvoz-t30f-h7jakme61mxb"
BASE_URL = "https://1aimko-tech-solutions-sl.hqrentals.eu"


# ─── Вспомогательные функции ────────────────────────────────────────────────────

def location_keyboard():
    """Клавиатура выбора локации (3 кнопки в ряд)."""
    buttons = []
    row = []
    for i, loc in enumerate(LOCATIONS):
        row.append(InlineKeyboardButton(loc, callback_data=f"loc:{loc}"))
        if (i + 1) % 2 == 0:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


def cancel_keyboard():
    return ReplyKeyboardMarkup([["❌ Отмена"]], resize_keyboard=True, one_time_keyboard=True)


def yes_no_keyboard():
    return ReplyKeyboardMarkup([["✅ Да, подтверждаю", "❌ Нет, отмена"]], resize_keyboard=True, one_time_keyboard=True)


# ─── Хэндлеры ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало диалога бронирования."""
    context.user_data.clear()
    user = update.effective_user
    name = user.first_name if user.first_name else "Гость"

    await update.message.reply_text(
        f"🚗 *Добро пожаловать в сервис аренды автомобилей Aimko Tech Solutions!*\n\n"
        f"Привет, {name}! Я помогу вам забронировать автомобиль быстро и удобно.\n\n"
        f"📍 *Шаг 1 из 6 — Место получения автомобиля*\n"
        f"Выберите локацию для получения авто:",
        parse_mode="Markdown",
        reply_markup=location_keyboard(),
    )
    return PICKUP_LOCATION


async def pickup_location_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатываем выбор места получения."""
    query = update.callback_query
    await query.answer()

    location = query.data.replace("loc:", "")
    context.user_data["pickup_location"] = location

    await query.edit_message_text(
        f"✅ Место получения: *{location}*\n\n"
        f"📍 *Шаг 2 из 6 — Место возврата автомобиля*\n"
        f"Выберите локацию для возврата авто:",
        parse_mode="Markdown",
        reply_markup=location_keyboard(),
    )
    return RETURN_LOCATION


async def return_location_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатываем выбор места возврата."""
    query = update.callback_query
    await query.answer()

    location = query.data.replace("loc:", "")
    context.user_data["return_location"] = location

    await query.edit_message_text(
        f"✅ Место возврата: *{location}*\n\n"
        f"📅 *Шаг 3 из 6 — Дата получения авто*\n"
        f"Введите дату получения в формате: *ДД-ММ-ГГГГ*\n"
        f"Пример: `15-07-2025`",
        parse_mode="Markdown",
    )
    return PICKUP_DATE


async def pickup_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получаем дату начала аренды."""
    text = update.message.text.strip()

    if text == "❌ Отмена":
        return await cancel(update, context)

    try:
        date = datetime.strptime(text, "%d-%m-%Y")
        if date.date() < datetime.now().date():
            await update.message.reply_text(
                "⚠️ Дата не может быть в прошлом. Введите дату заново:",
                reply_markup=cancel_keyboard(),
            )
            return PICKUP_DATE
        context.user_data["pickup_date"] = date.strftime("%d-%m-%Y")
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат даты. Используйте: *ДД-ММ-ГГГГ*\n"
            "Пример: `15-07-2025`",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard(),
        )
        return PICKUP_DATE

    await update.message.reply_text(
        f"✅ Дата получения: *{context.user_data['pickup_date']}*\n\n"
        f"🕐 *Шаг 4 из 6 — Время получения авто*\n"
        f"Введите время в формате: *ЧЧ:ММ*\n"
        f"Пример: `10:00`",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard(),
    )
    return PICKUP_TIME


async def pickup_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получаем время начала аренды."""
    text = update.message.text.strip()

    if text == "❌ Отмена":
        return await cancel(update, context)

    try:
        datetime.strptime(text, "%H:%M")
        context.user_data["pickup_time"] = text
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат времени. Используйте: *ЧЧ:ММ*\n"
            "Пример: `10:00`",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard(),
        )
        return PICKUP_TIME

    await update.message.reply_text(
        f"✅ Время получения: *{text}*\n\n"
        f"📅 *Шаг 5 из 6 — Дата возврата авто*\n"
        f"Введите дату возврата в формате: *ДД-ММ-ГГГГ*\n"
        f"Пример: `20-07-2025`",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard(),
    )
    return RETURN_DATE


async def return_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получаем дату конца аренды."""
    text = update.message.text.strip()

    if text == "❌ Отмена":
        return await cancel(update, context)

    try:
        date = datetime.strptime(text, "%d-%m-%Y")
        pickup = datetime.strptime(context.user_data["pickup_date"], "%d-%m-%Y")
        if date <= pickup:
            await update.message.reply_text(
                "⚠️ Дата возврата должна быть позже даты получения. Введите заново:",
                reply_markup=cancel_keyboard(),
            )
            return RETURN_DATE
        context.user_data["return_date"] = date.strftime("%d-%m-%Y")
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат даты. Используйте: *ДД-ММ-ГГГГ*\n"
            "Пример: `20-07-2025`",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard(),
        )
        return RETURN_DATE

    await update.message.reply_text(
        f"✅ Дата возврата: *{context.user_data['return_date']}*\n\n"
        f"🕐 *Шаг 6 из 6 — Время возврата авто*\n"
        f"Введите время в формате: *ЧЧ:ММ*\n"
        f"Пример: `18:00`",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard(),
    )
    return RETURN_TIME


async def return_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получаем время конца аренды и загружаем список авто."""
    text = update.message.text.strip()

    if text == "❌ Отмена":
        return await cancel(update, context)

    try:
        datetime.strptime(text, "%H:%M")
        context.user_data["return_time"] = text
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат времени. Используйте: *ЧЧ:ММ*\n"
            "Пример: `18:00`",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard(),
        )
        return RETURN_TIME

    # Показываем что делаем запрос
    loading_msg = await update.message.reply_text(
        "⏳ Ищу доступные автомобили... Пожалуйста, подождите.",
        reply_markup=ReplyKeyboardRemove(),
    )

    # Получаем список доступных авто через Playwright
    try:
        booking = CarRentalBooking(BASE_URL, BRAND_UUID)
        cars = await booking.get_available_cars(context.user_data)
        context.user_data["cars"] = cars
        context.user_data["booking_session"] = booking.ssid

        if not cars:
            await loading_msg.edit_text(
                "😔 К сожалению, на выбранные даты нет доступных автомобилей.\n"
                "Попробуйте изменить даты или локации. Введите /start для новой попытки."
            )
            return ConversationHandler.END

        # Формируем клавиатуру выбора авто
        buttons = []
        text_cars = "🚗 *Доступные автомобили:*\n\n"
        for i, car in enumerate(cars):
            price_text = f"{car.get('price', 'N/A')} €"
            car_text = (
                f"{i+1}. *{car['name']}*\n"
                f"   ⚙️ {car.get('category', '')}  |  💰 {price_text}\n"
            )
            if car.get('features'):
                car_text += f"   ✨ {car['features']}\n"
            text_cars += car_text + "\n"
            buttons.append([InlineKeyboardButton(
                f"{i+1}. {car['name']} — {price_text}",
                callback_data=f"car:{i}"
            )])

        buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])

        await loading_msg.edit_text(
            text_cars + "\nВыберите автомобиль:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    except Exception as e:
        logger.error(f"Ошибка при получении авто: {e}")
        await loading_msg.edit_text(
            "❌ Произошла ошибка при загрузке автомобилей. Попробуйте снова /start"
        )
        return ConversationHandler.END

    return SELECT_CAR


async def select_car_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь выбрал авто, собираем данные клиента."""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ Бронирование отменено. Введите /start для новой попытки.")
        return ConversationHandler.END

    car_idx = int(query.data.replace("car:", ""))
    car = context.user_data["cars"][car_idx]
    context.user_data["selected_car"] = car
    context.user_data["selected_car_idx"] = car_idx

    await query.edit_message_text(
        f"✅ Выбран: *{car['name']}*\n\n"
        f"👤 Теперь введите ваши данные для оформления бронирования.\n\n"
        f"*Имя (First name):*",
        parse_mode="Markdown",
    )
    return FIRST_NAME


async def first_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "❌ Отмена":
        return await cancel(update, context)
    if len(text) < 2:
        await update.message.reply_text("⚠️ Имя слишком короткое. Попробуйте снова:", reply_markup=cancel_keyboard())
        return FIRST_NAME
    context.user_data["first_name"] = text
    await update.message.reply_text("*Фамилия (Last name):*", parse_mode="Markdown", reply_markup=cancel_keyboard())
    return LAST_NAME


async def last_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "❌ Отмена":
        return await cancel(update, context)
    if len(text) < 2:
        await update.message.reply_text("⚠️ Фамилия слишком короткая. Попробуйте снова:", reply_markup=cancel_keyboard())
        return LAST_NAME
    context.user_data["last_name"] = text
    await update.message.reply_text("*Email адрес:*", parse_mode="Markdown", reply_markup=cancel_keyboard())
    return EMAIL


async def email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "❌ Отмена":
        return await cancel(update, context)
    if "@" not in text or "." not in text:
        await update.message.reply_text("❌ Неверный email. Попробуйте снова:", reply_markup=cancel_keyboard())
        return EMAIL
    context.user_data["email"] = text
    await update.message.reply_text(
        "*Номер телефона* (с кодом страны, пример: +34612345678):",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard(),
    )
    return PHONE


async def phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "❌ Отмена":
        return await cancel(update, context)
    cleaned = text.replace(" ", "").replace("-", "")
    if not cleaned.startswith("+") or len(cleaned) < 10:
        await update.message.reply_text(
            "❌ Неверный формат. Введите телефон с кодом страны: `+34612345678`",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard(),
        )
        return PHONE
    context.user_data["phone"] = text

    # Показываем итоговую сводку
    ud = context.user_data
    car = ud["selected_car"]
    summary = (
        f"📋 *Подтверждение бронирования*\n\n"
        f"🚗 *Автомобиль:* {car['name']}\n"
        f"💰 *Стоимость:* {car.get('price', 'N/A')} €\n\n"
        f"📍 *Получение:* {ud['pickup_location']}\n"
        f"📅 *Дата/время получения:* {ud['pickup_date']} в {ud['pickup_time']}\n\n"
        f"📍 *Возврат:* {ud['return_location']}\n"
        f"📅 *Дата/время возврата:* {ud['return_date']} в {ud['return_time']}\n\n"
        f"👤 *Клиент:* {ud['first_name']} {ud['last_name']}\n"
        f"📧 *Email:* {ud['email']}\n"
        f"📞 *Телефон:* {ud['phone']}\n\n"
        f"Всё верно?"
    )
    await update.message.reply_text(summary, parse_mode="Markdown", reply_markup=yes_no_keyboard())
    return CONFIRM_BOOKING


async def confirm_booking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Финальное подтверждение и отправка бронирования."""
    text = update.message.text.strip()

    if "Нет" in text or "Отмена" in text:
        return await cancel(update, context)

    if "Да" not in text:
        await update.message.reply_text("Пожалуйста, нажмите одну из кнопок:", reply_markup=yes_no_keyboard())
        return CONFIRM_BOOKING

    loading_msg = await update.message.reply_text(
        "⏳ Отправляю бронирование... Пожалуйста, подождите.",
        reply_markup=ReplyKeyboardRemove(),
    )

    try:
        booking = CarRentalBooking(BASE_URL, BRAND_UUID)
        result = await booking.complete_booking(context.user_data)

        if result["success"]:
            await loading_msg.edit_text(
                f"✅ *Бронирование успешно оформлено!*\n\n"
                f"🎫 *Номер бронирования:* `{result.get('booking_id', 'N/A')}`\n"
                f"📧 Подтверждение отправлено на: {context.user_data['email']}\n\n"
                f"Спасибо за выбор Aimko Tech Solutions! 🚗\n"
                f"Для нового бронирования введите /start",
                parse_mode="Markdown",
            )
        else:
            error_msg = result.get("error", "Неизвестная ошибка")
            await loading_msg.edit_text(
                f"❌ *Ошибка при оформлении бронирования*\n\n"
                f"Причина: {error_msg}\n\n"
                f"Пожалуйста, попробуйте снова /start или свяжитесь с нами.",
                parse_mode="Markdown",
            )

    except Exception as e:
        logger.error(f"Ошибка при бронировании: {e}")
        await loading_msg.edit_text(
            "❌ Произошла техническая ошибка. Пожалуйста, попробуйте снова /start"
        )

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена бронирования."""
    await update.message.reply_text(
        "❌ Бронирование отменено.\n\nВведите /start чтобы начать заново.",
        reply_markup=ReplyKeyboardRemove(),
    )
    context.user_data.clear()
    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🚗 *Aimko Car Rental Bot*\n\n"
        "Команды:\n"
        "/start — начать новое бронирование\n"
        "/cancel — отменить текущее бронирование\n"
        "/help — показать эту справку\n\n"
        "По любым вопросам обращайтесь к менеджеру.",
        parse_mode="Markdown",
    )


async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ответ на неизвестное сообщение вне диалога."""
    await update.message.reply_text(
        "Введите /start для начала бронирования автомобиля 🚗"
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Ошибка: {context.error}", exc_info=context.error)


# ─── Запуск бота ─────────────────────────────────────────────────────────────

def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN не задан в переменных окружения!")

    app = Application.builder().token(token).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            PICKUP_LOCATION: [CallbackQueryHandler(pickup_location_callback, pattern="^loc:")],
            RETURN_LOCATION: [CallbackQueryHandler(return_location_callback, pattern="^loc:")],
            PICKUP_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, pickup_date)],
            PICKUP_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, pickup_time)],
            RETURN_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, return_date)],
            RETURN_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, return_time)],
            SELECT_CAR: [CallbackQueryHandler(select_car_callback, pattern="^(car:|cancel)")],
            FIRST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, first_name)],
            LAST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, last_name)],
            EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, email)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, phone)],
            CONFIRM_BOOKING: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_booking)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex("^❌ Отмена$"), cancel),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message))
    app.add_error_handler(error_handler)

    logger.info("🚗 Бот запущен и готов к работе!")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
