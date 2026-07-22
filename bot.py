import asyncio
import logging
import re
import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, FSInputFile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== ВСТАВЬ СВОЙ НОВЫЙ ТОКЕН =====
BOT_TOKEN = "1850605284:AAG2VXv6f60X5ijV4ViRWZhZj4s7v7JXzxM"

dp = Dispatcher()

# Регулярка для ссылок Instagram
IG_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel|reels|tv)/([a-zA-Z0-9\-_]+)",
    re.IGNORECASE
)

async def get_instagram_media_url(post_url: str) -> str | None:
    """
    Ищет ссылку на видео/фото через публичный сервис SaveFrom.net (через его API).
    """
    # Используем открытый API SaveFrom (он стабильнее)
    api_url = f"https://api.savefrom.net/2/?url={post_url}&ajax=1"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(api_url, headers=headers, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Парсим ответ SaveFrom (всегда ищем ссылку в data)
                    if data.get("result") and len(data["result"]) > 0:
                        # Обычно ссылка лежит в первом элементе
                        media_url = data["result"][0].get("url")
                        if media_url:
                            return media_url
                else:
                    logger.error(f"API вернул статус: {resp.status}")
                    return None
        except Exception as e:
            logger.error(f"Ошибка при запросе к API: {e}")
            return None
    
    return None

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Я новый бот!\n"
        "Отправь ссылку на Instagram (пост или Reels).\n"
        "Я попробую найти видео через другой сервис."
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
    
    status_msg = await message.answer("⏳ Ищу файл через SaveFrom...")
    
    try:
        media_url = await get_instagram_media_url(post_url)
        
        if not media_url:
            await status_msg.edit_text("❌ Не удалось найти медиа. Сервис временно недоступен.")
            return
        
        # Скачиваем файл и отправляем
        async with aiohttp.ClientSession() as session:
            async with session.get(media_url) as resp:
                if resp.status == 200:
                    with open("temp_media.mp4", "wb") as f:
                        f.write(await resp.read())
                    await message.reply_video(FSInputFile("temp_media.mp4"), caption="✅ Готово! Вот твой файл.")
                    await status_msg.delete()
                else:
                    await status_msg.edit_text("❌ Ошибка загрузки файла.")
    except Exception as e:
        logger.exception(e)
        await status_msg.edit_text(f"❌ Ошибка: {e}")

async def main():
    bot = Bot(BOT_TOKEN)
    logger.info("🚀 Бот запущен (SaveFrom API)!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
