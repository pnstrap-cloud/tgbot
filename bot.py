import asyncio
import logging
import re
import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, FSInputFile
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== ТВОЙ ТОКЕН (ВСТАВЬ СЮДА) =====
BOT_TOKEN = "1850605284:AAGdzhUUV6Txu_7Lg6W09PbSg63W6M3XIro"

dp = Dispatcher()

# Регулярка для ссылок на Instagram (пост или Reels)
IG_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel|reels|tv)/([a-zA-Z0-9\-_]+)",
    re.IGNORECASE
)

# Функция для получения ссылки на медиа через сторонний API (Imginn)
async def get_instagram_media_url(post_url: str) -> str | None:
    """
    Пытается получить прямую ссылку на видео/фото через бесплатный парсер.
    """
    # Используем публичный API сайта Imginn (он работает без авторизации)
    api_url = f"https://api.imginn.com/api/getPost?url={post_url}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(api_url, headers=headers, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # В ответе обычно приходит поле video_url или image_url
                    if data.get("video_url"):
                        return data["video_url"]
                    elif data.get("image_url"):
                        return data["image_url"]
                    elif data.get("url"):
                        return data["url"]
                else:
                    logger.error(f"API вернул статус: {resp.status}")
                    return None
        except Exception as e:
            logger.error(f"Ошибка при запросе к API: {e}")
            return None

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Привет! Я новый бот.\n"
        "Просто отправь мне ссылку на пост или Reels из Instagram.\n"
        "Я постараюсь найти видео/фото через специальный сервис."
    )

@dp.message(F.text)
async def handle_message(message: Message):
    text = message.text
    match = IG_PATTERN.search(text)
    
    if not match:
        await message.answer("❌ Это не похоже на ссылку Instagram. Попробуй еще раз.")
        return

    shortcode = match.group(1)
    post_url = f"https://www.instagram.com/p/{shortcode}/"
    
    status_msg = await message.answer("⏳ Ищу файл через парсер...")
    
    try:
        media_url = await get_instagram_media_url(post_url)
        
        if not media_url:
            await status_msg.edit_text("❌ Не удалось найти медиа. Возможно, пост приватный или парсер временно недоступен.")
            return
        
        # Пытаемся скачать файл по ссылке и отправить
        async with aiohttp.ClientSession() as session:
            async with session.get(media_url) as resp:
                if resp.status == 200:
                    # Сохраняем во временный файл
                    with open("temp_media.mp4", "wb") as f:
                        f.write(await resp.read())
                    
                    # Отправляем файл пользователю
                    await message.reply_video(FSInputFile("temp_media.mp4"), caption="✅ Вот твой файл!")
                    await status_msg.delete()
                else:
                    await status_msg.edit_text("❌ Не удалось загрузить файл.")
    except Exception as e:
        logger.exception(e)
        await status_msg.edit_text(f"❌ Ошибка: {e}")

async def main():
    bot = Bot(BOT_TOKEN)
    logger.info("🚀 Новый бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
