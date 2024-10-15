import asyncio
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import (
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaDocument,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from googletrans import Translator

import os
from dotenv import load_dotenv

load_dotenv()

try:
    API_TOKEN = str(os.getenv("API_KEY"))
    SOURCE_CHANNEL_ID = os.getenv("SOURCE_CHANNEL_ID")
    ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", 0))
    DESTINATION_CHANNELS = {
        "en": int(os.getenv("DEST_CHANNEL_EN", 0)),
    }
    if int(os.getenv("DEST_CHANNEL_BE", 0)):
        DESTINATION_CHANNELS["be"] = int(os.getenv("DEST_CHANNEL_BE", 0))
except ValueError:
    raise ValueError("Please fill all required fields in .env file.")


if (
    not API_TOKEN
    or not SOURCE_CHANNEL_ID
    or not ADMIN_CHAT_ID
    or not DESTINATION_CHANNELS
):
    raise ValueError("Please fill all required fields in .env file.")

bot = Bot(token=API_TOKEN, parse_mode="html")
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

translator = Translator()

pending_media_groups = {}
message_cache = {}
moderation_enabled = True  # Флаг для включения/отключения модерации


class EditState(StatesGroup):
    waiting_for_new_text = State()


help_message = """
Если модерация включена, все сообщения из канала будут отправлены в административный чат для подтверждения.
Если модерация отключена, сообщения будут отправлены сразу в каналы.
Доступные команды:
/toggle_moderation - включить/отключить модерацию сообщений
/status - статус модерации 
/help - помощь
"""


@dp.message_handler(commands=["toggle_moderation"], chat_id=ADMIN_CHAT_ID)
async def toggle_moderation(message: types.Message):
    global moderation_enabled
    moderation_enabled = not moderation_enabled
    status = "включена" if moderation_enabled else "отключена"
    await message.reply(f"Модерация сообщений {status}. \n{help_message}")


@dp.message_handler(commands=["status"], chat_id=ADMIN_CHAT_ID)
async def status_command(message: types.Message):
    await message.reply(
        f"Модерация сообщений {'включена' if moderation_enabled else 'отключена'}. \n{help_message}"
    )


@dp.message_handler(commands=["help"], chat_id=ADMIN_CHAT_ID)
async def help_command(message: types.Message):
    await message.reply(help_message)


@dp.channel_post_handler(chat_id=SOURCE_CHANNEL_ID, content_types=types.ContentType.ANY)
async def handle_channel_messages(message: types.Message):
    if message.forward_date:
        return

    if message.media_group_id:
        if message.media_group_id not in pending_media_groups:
            pending_media_groups[message.media_group_id] = []
            asyncio.create_task(process_media_group(message.media_group_id))
        pending_media_groups[message.media_group_id].append(message)
    else:
        for lang, channel_id in DESTINATION_CHANNELS.items():
            text = message.parse_entities(as_html=True)
            translated_caption = translator.translate(text, dest=lang, src="ru").text

            if moderation_enabled:
                keyboard = InlineKeyboardMarkup().add(
                    InlineKeyboardButton(
                        f"✅ Подтвердить ({lang.upper()})",
                        callback_data=f"approve_{lang}_{message.message_id}",
                    ),
                    InlineKeyboardButton(
                        f"❌ Отклонить ({lang.upper()})",
                        callback_data=f"reject_{lang}_{message.message_id}",
                    ),
                    InlineKeyboardButton(
                        f"✏️ Редактировать ({lang.upper()})",
                        callback_data=f"edit_{lang}_{message.message_id}",
                    ),
                )

                if message.photo:
                    # Если есть фото, отправляем фото с подписью
                    photo = message.photo[-1].file_id
                    sent_message = await bot.send_photo(
                        ADMIN_CHAT_ID,
                        photo=photo,
                        caption=f"*Переведенное сообщение ({lang.upper()}):* \n{translated_caption}",
                        reply_markup=keyboard,
                        parse_mode="HTML",
                    )
                else:
                    # Если это только текст
                    sent_message = await bot.send_message(
                        ADMIN_CHAT_ID,
                        f"*Переведенное сообщение ({lang.upper()}):* \n{translated_caption}",
                        reply_markup=keyboard,
                        parse_mode="HTML",
                    )

                message_cache[f"{lang}_{message.message_id}"] = {
                    "original_message": message,
                    "sent_message": sent_message,
                    "lang": lang,
                }
            else:
                # Отправка сразу без модерации
                if message.photo:
                    photo = message.photo[-1].file_id
                    await bot.send_photo(
                        channel_id,
                        photo=photo,
                        caption=translated_caption,
                        parse_mode="HTML",
                    )
                else:
                    await bot.send_message(
                        channel_id,
                        translated_caption,
                        parse_mode="HTML",
                    )


async def process_media_group(media_group_id):
    await asyncio.sleep(1)  # Ждем, чтобы собрать все сообщения медиа-группы
    if media_group_id in pending_media_groups:
        media_group = pending_media_groups.pop(media_group_id)
        for lang, channel_id in DESTINATION_CHANNELS.items():
            keyboard = InlineKeyboardMarkup().add(
                InlineKeyboardButton(
                    f"✅ Подтвердить ({lang.upper()})",
                    callback_data=f"approve_{lang}_{media_group_id}",
                ),
                InlineKeyboardButton(
                    f"❌ Отклонить ({lang.upper()})",
                    callback_data=f"reject_{lang}_{media_group_id}",
                ),
                InlineKeyboardButton(
                    f"✏️ Редактировать ({lang.upper()})",
                    callback_data=f"edit_{lang}_{media_group_id}",
                ),
            )

            media_translations = []

            for idx, msg in enumerate(media_group):
                caption = msg.caption if msg.caption else ""
                translated_caption = (
                    translator.translate(caption, dest=lang, src="ru").text
                    if caption
                    else ""
                )
                if msg.content_type == "photo":
                    media_translations.append(
                        InputMediaPhoto(
                            media=msg.photo[-1].file_id,
                            caption=translated_caption if idx == 0 else "",
                        )
                    )
                elif msg.content_type == "video":
                    media_translations.append(
                        InputMediaVideo(
                            media=msg.video.file_id,
                            caption=translated_caption if idx == 0 else "",
                        )
                    )
                elif msg.content_type == "document":
                    media_translations.append(
                        InputMediaDocument(
                            media=msg.document.file_id,
                            caption=translated_caption if idx == 0 else "",
                        )
                    )
            if moderation_enabled:
                # Отправляем медиа-группы с переведенными подписями администратору
                sent_msgs = await bot.send_media_group(
                    ADMIN_CHAT_ID, media=media_translations
                )
                await bot.send_message(
                    ADMIN_CHAT_ID,
                    f"Выберите действие для канала ({lang.upper()}):",
                    reply_markup=keyboard,
                )

                # Сохраняем информацию о медиа-группе в кэш
                message_cache[f"{lang}_{media_group_id}"] = {
                    "original_messages": media_group,
                    "sent_messages": sent_msgs,
                    "media_translations": media_translations,
                    "lang": lang,
                }
            else:
                await bot.send_media_group(channel_id, media=media_translations)


@dp.callback_query_handler(lambda c: c.data.startswith("approve_"))
async def process_approve(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    _, lang, identifier = callback_query.data.split("_")
    if f"{lang}_{identifier}" in message_cache:
        data = message_cache.pop(f"{lang}_{identifier}")
        if "media_translations" in data:
            # Отправка в канал с соответствующим переводом
            await bot.send_media_group(
                DESTINATION_CHANNELS[lang], media=data["media_translations"]
            )
        else:
            message = data["original_message"]
            original_text = message.text or message.caption or ""
            translated_text = translator.translate(
                original_text, dest=lang, src="ru"
            ).text
            if message.photo:
                photo = message.photo[-1].file_id
                await bot.send_photo(
                    DESTINATION_CHANNELS[lang],
                    photo=photo,
                    caption=translated_text,
                    parse_mode="HTML",
                )
            else:
                await bot.send_message(
                    DESTINATION_CHANNELS[lang],
                    translated_text,
                    parse_mode="HTML",
                )
        try:
            await callback_query.message.edit_caption(
                f"Сообщение отправлено в канал ({lang.upper()})."
            )
        except:
            await callback_query.message.edit_text(
                f"Сообщение отправлено в канал ({lang.upper()})."
            )
    else:
        await bot.send_message(ADMIN_CHAT_ID, "Сообщение не найдено.")


@dp.callback_query_handler(lambda c: c.data.startswith("reject_"))
async def process_reject(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    _, lang, identifier = callback_query.data.split("_")
    if f"{lang}_{identifier}" in message_cache:
        message_cache.pop(f"{lang}_{identifier}")
        try:
            await callback_query.message.edit_caption(
                f"Сообщение отклонено для канала ({lang.upper()})."
            )
        except:
            await callback_query.message.edit_text(
                f"Сообщение отклонено для канала ({lang.upper()})."
            )

    else:
        await bot.send_message(ADMIN_CHAT_ID, "Сообщение не найдено.")


@dp.callback_query_handler(lambda c: c.data.startswith("edit_"))
async def process_edit(callback_query: types.CallbackQuery, state: FSMContext):
    await bot.answer_callback_query(callback_query.id)
    _, lang, identifier = callback_query.data.split("_")
    if f"{lang}_{identifier}" in message_cache:
        await state.update_data(
            identifier=identifier, lang=lang, callback_query=callback_query
        )
        await EditState.waiting_for_new_text.set()
        await bot.send_message(
            ADMIN_CHAT_ID,
            f"Отправьте новый текст сообщения для канала ({lang.upper()}):",
        )
    else:
        await bot.send_message(ADMIN_CHAT_ID, "Сообщение не найдено.")


@dp.message_handler(
    state=EditState.waiting_for_new_text, content_types=types.ContentType.TEXT
)
async def process_new_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    identifier = data.get("identifier")
    lang = data.get("lang")
    callback_query = data.get("callback_query")

    if f"{lang}_{identifier}" in message_cache:
        cache_data = message_cache.pop(f"{lang}_{identifier}")
        if "original_messages" in cache_data:
            media = []
            for idx, msg in enumerate(cache_data["original_messages"]):
                if msg.content_type == "photo":
                    media.append(
                        InputMediaPhoto(
                            media=msg.photo[-1].file_id,
                            caption=message.text if idx == 0 else "",
                        )
                    )
                elif msg.content_type == "video":
                    media.append(
                        InputMediaVideo(
                            media=msg.video.file_id,
                            caption=message.text if idx == 0 else "",
                        )
                    )
            await bot.send_media_group(DESTINATION_CHANNELS[lang], media=media)
        else:
            await bot.send_message(DESTINATION_CHANNELS[lang], message.text)

        await bot.send_message(
            ADMIN_CHAT_ID,
            f"Сообщение отредактировано и отправлено в канал ({lang.upper()}).",
        )
    else:
        await bot.send_message(ADMIN_CHAT_ID, "Сообщение не найдено.")
    await state.finish()


if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
