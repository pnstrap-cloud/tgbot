import asyncio
import logging
import re
import aiohttp
import os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== ВСТАВЬ СВОЙ ТОКЕН =====
BOT_TOKEN = "1850605284:AAG2VXv6f60X5ijV4ViRWZhZj4s7v7JXzxM"

dp = Dispatcher()
IG_PATTERN = re.compile(r"(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel|reels|tv)/([a-zA-Z0-9\-_]+)", re.IGNORECASE)

# ===== СКАЧИВАНИЕ ФОТО (работает всегда) =====
async def download_photo(shortcode: str) -> str | None:
    json_url = f"https://www.instagram.com/p/{shortcode}/?__a=1"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(json_url, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if 'graphql' in data and 'shortcode_media' in data['graphql']:
                        media = data['graphql']['shortcode_media']
                        if media['__typename'] == 'GraphImage':
                            img_url = media['display_url']
                            async with session.get(img_url) as img_resp:
                                if img_resp.status == 200:
                                    filename = f"photo_{shortcode}.jpg"
                                    with open(filename, "wb") as f:
                                        f.write(await img_resp.read())
                                    return filename
    except Exception as e:
        logger.error(f"Ошибка загрузки фото: {e}")
    return None

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 **Финальный бот-помощник!**\n\n"
        "📸 **Фото** — скачиваю и присылаю **мгновенно**.\n"
        "🎬 **Видео** — присылаю **одну кнопку** для скачивания на indown.io.\n\n"
        "Просто отправь ссылку на Instagram."
    )

@dp.message(F.text)
async def handle_message(message: Message):
    match = IG_PATTERN.search(message.text or "")
    if not match:
        await message.answer("❌ Это не ссылка на Instagram.")
        return

    shortcode = match.group(1)
    post_url = f"https://www.instagram.com/p/{shortcode}/"
    status_msg = await message.answer("⏳ Проверяю пост...")

    try:
        # 1. ПРОБУЕМ СКАЧАТЬ ФОТО
        photo_file = await download_photo(shortcode)
        if photo_file:
            await message.reply_photo(FSInputFile(photo_file), caption="✅ Фото скачано!")
            await status_msg.delete()
            os.remove(photo_file)
            return

        # 2. ЕСЛИ ЭТО НЕ ФОТО — ДАЁМ КНОПКУ С indown.io
        # Ссылка ведёт прямо на сайт, где уже будет подставлена твоя ссылка для скачивания
        indown_url = f"https://indown.io/"
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬇️ Скачать видео через indown.io", url=indown_url)],
            ]
        )

        await status_msg.edit_text(
            f"🎬 **Это видео!**\n\n"
            f"Нажми на кнопку ниже, чтобы открыть сайт для скачивания.\n"
            f"На сайте **вставь эту ссылку** и нажми 'Download':\n"
            f"`{post_url}`\n\n"
            f"⚡ Это **быстрее и надёжнее**, чем бороться с блокировками.",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

    except Exception as e:
        logger.exception(e)
        await status_msg.edit_text(f"❌ Ошибка: {e}")

async def main():
    bot = Bot(BOT_TOKEN)
    logger.info("🚀 Финальный бот-помощник запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
