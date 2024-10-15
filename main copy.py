import asyncio
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import (
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaDocument,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.utils.exceptions import MessageNotModified
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from googletrans import Translator


API_TOKEN = "7756503778:AAHyLUu0QK2CpH03Pgr9OpCX_jXeQek6l5A"
SOURCE_CHANNEL_ID = "-1001751958909"  ## тест 1
DESTINATION_CHANNEL_ID = -1001866342669  # тест 2
ADMIN_CHAT_ID = -1001777341484

bot = Bot(token=API_TOKEN, parse_mode="html")
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

translator = Translator()

pending_media_groups = {}
message_cache = {}


class EditState(StatesGroup):
    waiting_for_new_text = State()


async def process_media_group(media_group_id):
    await asyncio.sleep(1)  # Ждем, чтобы собрать все сообщения медиа-группы
    if media_group_id in pending_media_groups:
        media_group = pending_media_groups.pop(media_group_id)
        keyboard = InlineKeyboardMarkup().add(
            InlineKeyboardButton(
                "✅ Подтвердить", callback_data=f"approve_{media_group_id}"
            ),
            InlineKeyboardButton(
                "❌ Отклонить", callback_data=f"reject_{media_group_id}"
            ),
            InlineKeyboardButton(
                "✏️ Редактировать", callback_data=f"edit_{media_group_id}"
            ),
        )

        media = []
        translated_captions = []  # Список для переведенных подписей

        for idx, msg in enumerate(media_group):
            caption = msg.caption if msg.caption else ""
            translated_caption = translator.translate(caption, dest='en', src="ru").text if caption else ""
            translated_captions.append(translated_caption)

            # Создаем элементы медиа с переведенными подписями
            if msg.content_type == "photo":
                media.append(
                    InputMediaPhoto(media=msg.photo[-1].file_id, caption=translated_caption if idx == 0 else "")
                )
            elif msg.content_type == "video":
                media.append(
                    InputMediaVideo(media=msg.video.file_id, caption=translated_caption if idx == 0 else "")
                )
            elif msg.content_type == "document":
                media.append(
                    InputMediaDocument(media=msg.document.file_id, caption=translated_caption if idx == 0 else "")
                )

        # Отправляем медиа-группу с переведенными подписями администратору
        sent_msgs = await bot.send_media_group(ADMIN_CHAT_ID, media=media)
        await bot.send_message(ADMIN_CHAT_ID, "Выберите действие:", reply_markup=keyboard)

        # Сохраняем информацию о медиа-группе в кэш
        message_cache[str(media_group_id)] = {
            "original_messages": media_group,
            "sent_messages": sent_msgs,
        }


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
        text = message.parse_entities(as_html=True)
        translated_caption = translator.translate(text, dest='en', src="ru").text
        message.text = translated_caption

        keyboard = InlineKeyboardMarkup().add(
            InlineKeyboardButton(
                "✅ Подтвердить", callback_data=f"approve_{message.message_id}"
            ),
            InlineKeyboardButton(
                "❌ Отклонить", callback_data=f"reject_{message.message_id}"
            ),
            InlineKeyboardButton(
                "✏️ Редактировать", callback_data=f"edit_{message.message_id}"
            ),
        )
        if message.photo:
            # Если есть фото, отправляем фото с подписью
            photo = message.photo[-1].file_id
            sent_message = await bot.send_photo(
                ADMIN_CHAT_ID,
                photo=photo,
                caption=f"*Переведенное сообщение:* \n{translated_caption}",
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        else:
            # Если это только текст
            sent_message = await bot.send_message(
                ADMIN_CHAT_ID,
                f"*Переведенное сообщение:* \n{translated_caption}",
                reply_markup=keyboard,
                parse_mode="HTML",
            )

        message_cache[str(message.message_id)] = {
            "original_message": message,
            "sent_message": sent_message,
        }


@dp.callback_query_handler(lambda c: c.data.startswith("approve_"))
async def process_approve(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    identifier = callback_query.data.split("_")[1]
    if identifier in message_cache:
        data = message_cache.pop(identifier)
        if "original_messages" in data:
            media = []
            for msg in data["original_messages"]:
                caption = msg.caption if msg.caption else ""
                translated_caption = translator.translate(caption, dest='en', src="ru").text if caption else ""

                if msg.content_type == "photo":
                    media.append(InputMediaPhoto(media=msg.photo[-1].file_id, caption=translated_caption))
                elif msg.content_type == "video":
                    media.append(InputMediaVideo(media=msg.video.file_id, caption=translated_caption))
                elif msg.content_type == "document":
                    media.append(InputMediaDocument(media=msg.document.file_id, caption=translated_caption))

            await bot.send_media_group(DESTINATION_CHANNEL_ID, media=media)
        else:
            message = data["original_message"]
            if message.photo:
                photo = message.photo[-1].file_id
                await bot.send_photo(
                    DESTINATION_CHANNEL_ID,
                    photo=photo,
                    caption=message.text,
                    parse_mode="HTML",
                )
            else:
                await bot.send_message(
                    DESTINATION_CHANNEL_ID,
                    message.text,
                    parse_mode="HTML",
                )

        await bot.send_message(ADMIN_CHAT_ID, "Сообщение отправлено.")
    else:
        await bot.send_message(ADMIN_CHAT_ID, "Сообщение не найдено.")



@dp.callback_query_handler(lambda c: c.data.startswith("reject_"))
async def process_reject(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    identifier = callback_query.data.split("_")[1]
    if identifier in message_cache:
        message_cache.pop(identifier)
        await bot.send_message(ADMIN_CHAT_ID, "Сообщение отклонено.")
    else:
        await bot.send_message(ADMIN_CHAT_ID, "Сообщение не найдено.")


@dp.callback_query_handler(lambda c: c.data.startswith("edit_"))
async def process_edit(callback_query: types.CallbackQuery, state: FSMContext):
    await bot.answer_callback_query(callback_query.id)
    identifier = str(callback_query.data.split("_", 1)[1])
    if identifier in message_cache:
        await state.update_data(identifier=identifier)
        await EditState.waiting_for_new_text.set()
        await bot.send_message(ADMIN_CHAT_ID, "Отправьте новый текст сообщения.")
    else:
        await bot.send_message(ADMIN_CHAT_ID, "Сообщение не найдено.")


@dp.message_handler(state=EditState.waiting_for_new_text, content_types=types.ContentType.TEXT)
async def process_new_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    identifier = data.get("identifier")

    if identifier in message_cache:
        cache_data = message_cache.pop(identifier)
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
            await bot.send_media_group(DESTINATION_CHANNEL_ID, media=media)
        else:
            await bot.send_message(DESTINATION_CHANNEL_ID, message.text)
        await bot.send_message(ADMIN_CHAT_ID, "Сообщение отредактировано и отправлено.")
    else:
        await bot.send_message(ADMIN_CHAT_ID, "Сообщение не найдено.")
    await state.finish()


if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
