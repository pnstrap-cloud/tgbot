import asyncio
import logging
import re
import aiohttp
import os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, FSInputFile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== ВСТАВЬ СВОЙ ТОКЕН =====
BOT_TOKEN = "1850605284:AAG2VXv6f60X5ijV4ViRWZhZj4s7v7JXzxM"

dp = Dispatcher()
IG_PATTERN = re.compile(r"(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel|reels|tv)/([a-zA-Z0-9\-_]+)", re.IGNORECASE)

# ===== НОВЫЙ РАБОЧИЙ ПАРСЕР (InDown.io) =====
async def get_media_from_indown(url: str) -> str | None:
    """
    Использует API сервиса InDown.io для получения прямой ссылки.
    Этот сервис пока стабильно работает без блокировок.
    """
    api_url = "https://indown.io/api/v1/get"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
    }
    
    payload = {
        "url": url
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            # Отправляем POST-запрос к API
            async with session.post(api_url, json=payload, headers=headers, timeout=20) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.info(f"InDown ответ: {data}")
                    
                    # Проверяем наличие видео или фото
                    if data.get("success"):
                        # Сначала проверяем видео (High Quality)
                        if data.get("video_hd"):
                            return data["video_hd"]
                        elif data.get("video"):
                            return data["video"]
                        elif data.get("image"):
                            return data["image"] # Ссылка на фото
                    else:
                        logger.error(f"InDown ошибка: {data.get('error')}")
                else:
                    logger.error(f"InDown статус: {resp.status}")
                    return None
        except Exception as e:
            logger.error(f"Ошибка InDown: {e}")
            return None
    return None

async def download_file(url: str, filename: str) -> str | None:
    """Скачивает файл по ссылке."""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=30) as resp:
                if resp.status == 200:
                    content = await resp.read()
                    if len(content) > 1024:
                        with open(filename, "wb") as f:
                            f.write(content)
                        return filename
                else:
                    logger.error(f"Ошибка скачивания: {resp.status}")
        except Exception as e:
            logger.error(f"Ошибка при скачивании: {e}")
    return None

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Привет! Я бот-скачиватель из Instagram.\n"
        "📸 Отправь ссылку — я пришлю видео или фото!\n"
        "⚡ Работает через новый стабильный сервис."
    )

@dp.message(F.text)
async def handle_message(message: Message):
    text = message.text
    match = IG_PATTERN.search(text)
    if not match:
        await message.answer("❌ Это не ссылка Instagram.")
        return

    shortcode = match.group(1)
    post_url = f"https://www.instagram.com/p/{shortcode}/"
    
    status_msg = await message.answer("⏳ Ищу медиа через InDown...")
    
    try:
        media_url = await get_media_from_indown(post_url)
        
        if not media_url:
            # Если API не сработал, даём ссылку на ручной ввод
            await status_msg.edit_text(
                f"❌ Не удалось скачать автоматически.\n\n"
                f"Попробуй вручную вставить ссылку на сайте:\n"
                f"https://indown.io/\n\n"
                f"📌 Твоя ссылка: {post_url}"
            )
            return

        # Определяем расширение
        if ".mp4" in media_url or ".mov" in media_url:
            ext, caption = "mp4", "✅ Видео скачано!"
        else:
            ext, caption = "jpg", "✅ Фото скачано!"

        filename = f"temp_media.{ext}"
        
        await status_msg.edit_text("⏳ Скачиваю файл...")
        downloaded = await download_file(media_url, filename)
        
        if not downloaded:
            await status_msg.edit_text("❌ Ошибка при скачивании файла.")
            return
        
        await status_msg.edit_text("📤 Отправляю...")
        
        if ext == "mp4":
            await message.reply_video(FSInputFile(filename), caption=caption)
        else:
            await message.reply_photo(FSInputFile(filename), caption=caption)
        
        await status_msg.delete()
        os.remove(filename)
        
    except Exception as e:
        logger.exception(e)
        await status_msg.edit_text(f"❌ Ошибка: {e}")

async def main():
    bot = Bot(BOT_TOKEN)
    logger.info("🚀 Бот через InDown API запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
