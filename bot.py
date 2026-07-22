import asyncio
import logging
import re
import aiohttp
import os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from yt_dlp import YoutubeDL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== ВСТАВЬ СВОЙ ТОКЕН =====
BOT_TOKEN = "1850605284:AAG2VXv6f60X5ijV4ViRWZhZj4s7v7JXzxM"

dp = Dispatcher()
IG_PATTERN = re.compile(r"(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel|reels|tv)/([a-zA-Z0-9\-_]+)", re.IGNORECASE)

# Попытка скачать через yt-dlp (без сессии, только прямые ссылки)
async def try_direct_download(url: str) -> str | None:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": False,
        "outtmpl": "temp_media.%(ext)s",
        "format": "best[ext=mp4]/best[ext=mp4]/best",
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # Проверяем, скачался ли файл
            for file in os.listdir('.'):
                if file.startswith('temp_media.') and os.path.getsize(file) > 1024:
                    return file
    except Exception as e:
        logger.error(f"Ошибка yt-dlp: {e}")
    return None

# Попытка скачать фото напрямую через requests (часто работает без сессии)
async def try_download_photo(url: str) -> str | None:
    # Пытаемся получить JSON с прямой ссылкой на фото
    json_url = url.replace("/p/", "/p/").split('?')[0] + "?__a=1"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(json_url, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Ищем ссылку на фото
                    if 'graphql' in data and 'shortcode_media' in data['graphql']:
                        media = data['graphql']['shortcode_media']
                        if media['__typename'] == 'GraphImage':
                            img_url = media['display_url']
                            # Скачиваем фото
                            async with session.get(img_url) as img_resp:
                                if img_resp.status == 200:
                                    with open("temp_media.jpg", "wb") as f:
                                        f.write(await img_resp.read())
                                    return "temp_media.jpg"
    except Exception as e:
        logger.error(f"Ошибка загрузки фото: {e}")
    return None

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Привет! Я умею скачивать фото и видео из Instagram.\n"
        "Просто отправь ссылку на пост или Reels.\n\n"
        "📸 Если это фото — я скачаю его сразу.\n"
        "🎬 Если это видео — я попробую скачать, а если не получится — дам ссылку для скачивания."
    )

@dp.message(F.text)
async def handle_message(message: Message):
    text = message.text
    match = IG_PATTERN.search(text)
    if not match:
        await message.answer("❌ Это не ссылка на Instagram.")
        return

    shortcode = match.group(1)
    post_url = f"https://www.instagram.com/p/{shortcode}/"
    
    status_msg = await message.answer("⏳ Пробую скачать напрямую...")
    
    try:
        # Сначала пробуем скачать как фото (это часто работает)
        photo_file = await try_download_photo(post_url)
        if photo_file:
            await message.reply_photo(FSInputFile(photo_file), caption="✅ Фото скачано!")
            await status_msg.delete()
            os.remove(photo_file)
            return
        
        # Если фото не скачалось, пробуем скачать как видео
        video_file = await try_direct_download(post_url)
        if video_file:
            await message.reply_video(FSInputFile(video_file), caption="✅ Видео скачано!")
            await status_msg.delete()
            os.remove(video_file)
            return
        
        # Если ничего не скачалось — даём кнопки с сайтами-парсерами
        parser_links = [
            f"https://snapinsta.app/instagram-downloader/?url={post_url}",
            f"https://savefrom.net/ru/#url={post_url}"
        ]
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📥 Скачать через SnapInsta", url=parser_links[0])],
                [InlineKeyboardButton(text="📥 Скачать через SaveFrom", url=parser_links[1])],
            ]
        )
        await status_msg.edit_text(
            "❌ Не удалось скачать напрямую.\n\n"
            "Но ты можешь скачать через сайты-парсеры:",
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.exception(e)
        await status_msg.edit_text(f"❌ Ошибка: {e}")

async def main():
    bot = Bot(BOT_TOKEN)
    logger.info("🚀 Гибридный бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
