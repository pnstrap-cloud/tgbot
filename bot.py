import asyncio
import logging
import re
import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== ВСТАВЬ СВОЙ ТОКЕН =====
BOT_TOKEN = "1850605284:AAG2VXv6f60X5ijV4ViRWZhZj4s7v7JXzxM"

dp = Dispatcher()

# Регулярка для Instagram
IG_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel|reels|tv)/([a-zA-Z0-9\-_]+)",
    re.IGNORECASE
)

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Привет! Я бот-помощник для скачивания из Instagram.\n\n"
        "📌 Отправь ссылку на пост или Reels — я дам тебе прямую ссылку для скачивания в высоком качестве.\n\n"
        "🔹 Ссылка откроется в браузере — там можно сохранить видео или фото."
    )

@dp.message(F.text)
async def handle_message(message: Message):
    text = message.text
    match = IG_PATTERN.search(text)
    
    if not match:
        await message.answer("❌ Это не похоже на ссылку Instagram. Попробуй ещё раз.")
        return

    shortcode = match.group(1)
    post_url = f"https://www.instagram.com/p/{shortcode}/"
    
    # Используем публичный сайт для скачивания (работает без API)
    # Это сайт-парсер, который можно открыть в браузере
    download_url = f"https://www.instagram.com/p/{shortcode}/?__a=1"
    
    # Альтернативный способ: даём ссылку на сайт-парсер
    # Этот сайт позволяет скачать видео/фото из Instagram
    parser_links = [
        f"https://igram.io/instagram-downloader/?url={post_url}",
        f"https://snapinsta.app/instagram-downloader/?url={post_url}",
        f"https://savefrom.net/ru/#url={post_url}"
    ]
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📥 Скачать через iGram", url=parser_links[0])],
            [InlineKeyboardButton(text="📥 Скачать через SnapInsta", url=parser_links[1])],
            [InlineKeyboardButton(text="📥 Скачать через SaveFrom", url=parser_links[2])],
        ]
    )
    
    await message.answer(
        f"✅ Нашёл пост!\n\n"
        f"🔗 Ссылка на пост: {post_url}\n\n"
        f"📌 Нажми на одну из кнопок ниже — откроется сайт, где можно скачать видео или фото.\n\n"
        f"⚡ Если один сайт не работает — попробуй другой.",
        reply_markup=keyboard
    )

async def main():
    bot = Bot(BOT_TOKEN)
    logger.info("🚀 Бот-помощник запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
