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
BOT_TOKEN = "1850605284:AAEsZpYP2u679yaQL1gLpMte7vB1EMOw8p4"

dp = Dispatcher()

# Регулярка для Instagram
IG_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel|reels|tv)/([a-zA-Z0-9\-_]+)",
    re.IGNORECASE
)

# ===== API SAVEFROM (без рекламы) =====
async def get_media_from_savefrom(url: str) -> str | None:
    """
    Использует публичный API SaveFrom для получения прямой ссылки на медиа.
    """
    # SaveFrom API endpoint
    api_url = "https://savefrom.net/2/"
    
    params = {
        "url": url,
        "ajax": "1",
        "format": "json"
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://savefrom.net/",
        "X-Requested-With": "XMLHttpRequest",
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(api_url, params=params, headers=headers, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.info(f"Ответ SaveFrom: {data}")
                    
                    # Парсим ответ
                    if data.get("result") and len(data["result"]) > 0:
                        # Обычно ссылка на видео в первом элементе
                        media = data["result"][0]
                        if media.get("url"):
                            return media["url"]
                        
                        # Если ссылки нет, ищем вложенные
                        if media.get("links") and len(media["links"]) > 0:
                            return media["links"][0].get("url")
                else:
                    logger.error(f"SaveFrom вернул статус: {resp.status}")
                    return None
        except Exception as e:
            logger.error(f"Ошибка запроса к SaveFrom: {e}")
            return None
    
    return None

async def download_file(url: str, filename: str) -> str | None:
    """Скачивает файл по ссылке."""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=30) as resp:
                if resp.status == 200:
                    content = await resp.read()
                    if len(content) > 1024:  # Проверка, что файл не пустой
                        with open(filename, "wb") as f:
                            f.write(content)
                        return filename
                else:
                    logger.error(f"Ошибка скачивания файла: {resp.status}")
        except Exception as e:
            logger.error(f"Ошибка при скачивании: {e}")
    return None

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Привет! Я бот-скачиватель из Instagram.\n"
        "📸 Отправь ссылку на пост или Reels — я скачаю видео или фото и пришлю тебе!\n\n"
        "⚡ Работает через SaveFrom — быстро и без рекламы!"
    )

@dp.message(F.text)
async def handle_message(message: Message):
    text = message.text
    match = IG_PATTERN.search(text)
    
    if not match:
        await message.answer("❌ Это не похоже на ссылку Instagram.")
        return

    shortcode = match.group(1)
    post_url = f"https://www.instagram.com/p/{shortcode}/"
    
    status_msg = await message.answer("⏳ Ищу медиа через SaveFrom...")
    
    try:
        # Получаем ссылку на медиа через SaveFrom
        media_url = await get_media_from_savefrom(post_url)
        
        if not media_url:
            await status_msg.edit_text(
                "❌ Не удалось найти медиа.\n\n"
                "Попробуй другой сервис: https://snapinsta.app"
            )
            return
        
        # Определяем расширение файла (видео или фото)
        if ".mp4" in media_url or ".mov" in media_url:
            ext = "mp4"
            file_type = "видео"
        else:
            ext = "jpg"
            file_type = "фото"
        
        filename = f"temp_media.{ext}"
        
        # Скачиваем файл
        await status_msg.edit_text(f"⏳ Скачиваю {file_type}...")
        downloaded = await download_file(media_url, filename)
        
        if not downloaded:
            await status_msg.edit_text("❌ Не удалось скачать файл.")
            return
        
        # Отправляем файл
        await status_msg.edit_text("📤 Отправляю...")
        
        if ext == "mp4":
            await message.reply_video(FSInputFile(filename), caption="✅ Видео скачано!")
        else:
            await message.reply_photo(FSInputFile(filename), caption="✅ Фото скачано!")
        
        # Удаляем статус и временный файл
        await status_msg.delete()
        os.remove(filename)
        
    except Exception as e:
        logger.exception(e)
        await status_msg.edit_text(f"❌ Ошибка: {e}")

async def main():
    bot = Bot(BOT_TOKEN)
    logger.info("🚀 Бот через SaveFrom API запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
