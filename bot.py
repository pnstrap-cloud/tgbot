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

# ===== НОВАЯ ВЕРСИЯ API SAVEFROM (с эмуляцией браузера) =====
async def get_media_from_savefrom(url: str) -> str | None:
    api_url = "https://savefrom.net/2/"
    params = {
        "url": url,
        "ajax": "1",
        "format": "json",
    }
    
    # Критично важные заголовки, как в браузере
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://savefrom.net/ru/", # Явно указываем реферер
        "X-Requested-With": "XMLHttpRequest",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            # Сначала получаем главную страницу, чтобы получить куки
            await session.get("https://savefrom.net/ru/", headers=headers)
            
            # Теперь отправляем запрос к API с полученными куками
            async with session.get(api_url, params=params, headers=headers, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.info(f"Ответ SaveFrom: {data}")
                    
                    if data.get("result") and len(data["result"]) > 0:
                        media = data["result"][0]
                        # Проверяем разные варианты размещения ссылки
                        if media.get("url"):
                            return media["url"]
                        if media.get("links") and len(media["links"]) > 0:
                            # Ищем ссылку с высоким качеством
                            for link in media["links"]:
                                if link.get("quality") == "720p" or link.get("quality") == "1080p" or link.get("quality") == "high":
                                    return link.get("url")
                            return media["links"][0].get("url")
                else:
                    logger.error(f"SaveFrom вернул статус: {resp.status}")
                    return None
        except Exception as e:
            logger.error(f"Ошибка запроса к SaveFrom: {e}")
            return None
    return None

async def download_file(url: str, filename: str) -> str | None:
    async with aiohttp.ClientSession() as session:
        try:
            # Добавляем заголовки и для скачивания
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "Referer": "https://savefrom.net/",
            }
            async with session.get(url, headers=headers, timeout=30) as resp:
                if resp.status == 200:
                    content = await resp.read()
                    if len(content) > 1024:
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
    await message.answer("👋 Отправь ссылку на Instagram — я скачаю видео или фото!")

@dp.message(F.text)
async def handle_message(message: Message):
    match = IG_PATTERN.search(message.text or "")
    if not match:
        await message.answer("❌ Это не ссылка Instagram.")
        return

    post_url = f"https://www.instagram.com/p/{match.group(1)}/"
    status_msg = await message.answer("⏳ Ищу через SaveFrom...")
    
    try:
        media_url = await get_media_from_savefrom(post_url)
        if not media_url:
            await status_msg.edit_text(
                "❌ Не удалось найти медиа. Попробуй другой сервис: https://snapinsta.app"
            )
            return

        # Определяем тип файла
        ext = "mp4" if (".mp4" in media_url or ".mov" in media_url) else "jpg"
        file_type = "видео" if ext == "mp4" else "фото"
        filename = f"temp_media.{ext}"
        
        await status_msg.edit_text(f"⏳ Скачиваю {file_type}...")
        downloaded = await download_file(media_url, filename)
        
        if not downloaded:
            await status_msg.edit_text("❌ Не удалось скачать файл.")
            return
        
        await status_msg.edit_text("📤 Отправляю...")
        if ext == "mp4":
            await message.reply_video(FSInputFile(filename), caption="✅ Видео скачано!")
        else:
            await message.reply_photo(FSInputFile(filename), caption="✅ Фото скачано!")
        
        await status_msg.delete()
        os.remove(filename)
        
    except Exception as e:
        logger.exception(e)
        await status_msg.edit_text(f"❌ Ошибка: {e}")

async def main():
    bot = Bot(BOT_TOKEN)
    logger.info("🚀 Бот через SaveFrom API (с куками) запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
