"""
Telegram-бот для скачивания видео из Instagram и TikTok через yt-dlp.

Установка:
    pip install aiogram yt-dlp

Запуск:
    export BOT_TOKEN="ваш_токен_от_BotFather"
    python bot.py
"""

import asyncio
import logging
import os
import re
import tempfile
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, Message
from yt_dlp import YoutubeDL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = "1850605284:AAEsZpYP2u679yaQL1gLpMte7vB1EMOw8p4"


# 50 МБ — лимит Telegram Bot API на отправку файлов
TG_SIZE_LIMIT = 50 * 1024 * 1024

URL_RE = re.compile(
    r"https?://(?:www\.)?(?:instagram\.com/(?:p|reel|reels|tv)/[\w\-]+"
    r"|tiktok\.com/[^\s]+"
    r"|vm\.tiktok\.com/[^\s]+"
    r"|vt\.tiktok\.com/[^\s]+)",
    re.IGNORECASE,
)
)

dp = Dispatcher()


def download_video(url: str, out_dir: str) -> Path:
    """Синхронно скачивает видео и возвращает путь к файлу."""
    ydl_opts = {
        "outtmpl": os.path.join(out_dir, "%(id)s.%(ext)s"),
        "format": "mp4/bestvideo*+bestaudio/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "restrictfilenames": True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        # если merge случился — расширение может измениться
        filename = ydl.prepare_filename(info)
        path = Path(filename)
        if not path.exists():
            # ищем что реально скачалось
            candidates = list(Path(out_dir).iterdir())
            if not candidates:
                raise FileNotFoundError("yt-dlp не создал файл")
            path = candidates[0]
        return path


@dp.message(CommandStart())
async def on_start(message: Message) -> None:
    await message.answer(
        "Привет! Пришли мне ссылку на видео из Instagram или TikTok, "
        "и я его скачаю и отправлю обратно."
    )


@dp.message(F.text.regexp(URL_RE))
async def on_link(message: Message) -> None:
    match = URL_RE.search(message.text or "")
    if not match:
        return
    url = match.group(0)

    status = await message.reply("⏬ Скачиваю видео...")

    with tempfile.TemporaryDirectory() as tmp:
        try:
            path = await asyncio.to_thread(download_video, url, tmp)
        except Exception as e:
            logger.exception("Ошибка при скачивании")
            await status.edit_text(f"❌ Не удалось скачать: {e}")
            return

        size = path.stat().st_size
        if size > TG_SIZE_LIMIT:
            await status.edit_text(
                f"❌ Видео слишком большое ({size / 1024 / 1024:.1f} МБ). "
                f"Лимит Telegram Bot API — 50 МБ."
            )
            return

        await status.edit_text("📤 Отправляю...")
        try:
            await message.reply_video(FSInputFile(path), caption=url)
            await status.delete()
        except Exception as e:
            logger.exception("Ошибка при отправке")
            await status.edit_text(f"❌ Не удалось отправить: {e}")


@dp.message()
async def on_other(message: Message) -> None:
    await message.reply("Пришли ссылку на видео из Instagram или TikTok.")


async def main() -> None:
    bot = Bot(BOT_TOKEN)
    logger.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
