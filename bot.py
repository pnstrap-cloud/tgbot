import asyncio
import logging
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Optional

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)
from yt_dlp import YoutubeDL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== ТВОЙ ТОКЕН (ВСТАВЬ СВОЙ) =====
BOT_TOKEN = "1850605284:AAG2VXv6f60X5ijV4ViRWZhZj4s7v7JXzxM"

# 50 МБ — лимит Telegram Bot API на отправку файлов
TG_SIZE_LIMIT = 50 * 1024 * 1024

# ===== РЕГУЛЯРКА ДЛЯ ССЫЛОК (ДОБАВЛЕН PINTEREST) =====
URL_RE = re.compile(
    r"https?://(?:www\.)?"
    r"(?:instagram\.com/(?:p|reel|reels|tv)/[\w\-]+"
    r"|tiktok\.com/[^\s]+"
    r"|vm\.tiktok\.com/[^\s]+"
    r"|vt\.tiktok\.com/[^\s]+"
    r"|pinterest\.[\w.]+/pin/[\w\-]+"
    r"|pin\.it/[\w\-]+)",  # Короткие ссылки Pinterest
    re.IGNORECASE,
)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm"}

dp = Dispatcher()

# Хранилище подписей: caption_id -> текст
captions_store: dict[str, str] = {}


def make_caption_kb(caption_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Показать подпись", callback_data=f"cap:{caption_id}")]
        ]
    )


def download_media(url: str, out_dir: str) -> tuple[list[Path], dict]:
    """Скачивает медиа. Возвращает (список путей, info dict)."""
    ydl_opts = {
        "outtmpl": os.path.join(out_dir, "%(id)s.%(ext)s"),
        "format": "best[ext=mp4]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": False,
        "restrictfilenames": True,
        "ignoreerrors": True,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    files = sorted(
        [p for p in Path(out_dir).iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS | VIDEO_EXTS]
    )
    return files, info or {}


def extract_caption(info: dict) -> str:
    """Достаёт описание/подпись из info yt-dlp."""
    if not info:
        return ""
    for key in ("description", "title"):
        v = info.get(key)
        if v and isinstance(v, str) and v.strip():
            if key == "title" and len(v) < 5:
                continue
            return v.strip()
    entries = info.get("entries") or []
    for e in entries:
        if not e:
            continue
        for key in ("description", "title"):
            v = e.get(key)
            if v and isinstance(v, str) and v.strip():
                return v.strip()
    return ""


def store_caption(text: str) -> str:
    cid = uuid.uuid4().hex[:12]
    captions_store[cid] = text or ""
    return cid


@dp.message(CommandStart())
async def on_start(message: Message) -> None:
    await message.answer(
        "Привет! Пришли ссылку из:\n"
        "• Instagram\n"
        "• TikTok\n"
        "• Pinterest\n\n"
        "Я скачаю видео/фото и покажу подпись по кнопке."
    )


@dp.message(F.text.regexp(URL_RE))
async def on_link(message: Message) -> None:
    match = URL_RE.search(message.text or "")
    if not match:
        return
    url = match.group(0)

    status = await message.reply("⏬ Скачиваю...")

    with tempfile.TemporaryDirectory() as tmp:
        try:
            files, info = await asyncio.to_thread(download_media, url, tmp)
        except Exception as e:
            logger.exception("Ошибка при скачивании")
            await status.edit_text(f"❌ Не удалось скачать: {e}")
            return

        if not files:
            await status.edit_text("❌ Не удалось получить медиа по этой ссылке.")
            return

        caption_text = extract_caption(info)
        caption_id = store_caption(caption_text)
        kb = make_caption_kb(caption_id)

        # Фильтруем по размеру
        ok_files = []
        for p in files:
            if p.stat().st_size > TG_SIZE_LIMIT:
                logger.warning("Файл %s больше 50 МБ, пропуск", p)
                continue
            ok_files.append(p)

        if not ok_files:
            await status.edit_text("❌ Все файлы больше 50 МБ (лимит Telegram).")
            return

        await status.edit_text("📤 Отправляю...")

        try:
            # Определяем тип файлов
            images = [p for p in ok_files if p.suffix.lower() in IMAGE_EXTS]
            videos = [p for p in ok_files if p.suffix.lower() in VIDEO_EXTS]

            # Отправляем фото
            if images:
                if len(images) == 1 and not videos:
                    await message.reply_photo(FSInputFile(images[0]), reply_markup=kb)
                else:
                    for chunk_start in range(0, len(images), 10):
                        chunk = images[chunk_start:chunk_start + 10]
                        media = [InputMediaPhoto(media=FSInputFile(p)) for p in chunk]
                        await message.reply_media_group(media)
                    if not videos:
                        await message.reply("Медиа отправлено.", reply_markup=kb)

            # Отправляем видео
            for i, v in enumerate(videos):
                markup = kb if (i == len(videos) - 1) else None
                await message.reply_video(FSInputFile(v), reply_markup=markup)

            await status.delete()
        except Exception as e:
            logger.exception("Ошибка при отправке")
            await status.edit_text(f"❌ Не удалось отправить: {e}")


@dp.callback_query(F.data.startswith("cap:"))
async def on_caption(cb: CallbackQuery) -> None:
    cid = cb.data.split(":", 1)[1]
    text = captions_store.get(cid)
    if text is None:
        await cb.answer("Подпись больше недоступна.", show_alert=True)
        return
    await cb.answer()
    if text.strip():
        await cb.message.reply(text[:4000])
    else:
        await cb.message.reply("Подписи к этому медиа нет.")


@dp.message()
async def on_other(message: Message) -> None:
    await message.reply("Пришли ссылку из Instagram, TikTok или Pinterest.")


async def main() -> None:
    bot = Bot(BOT_TOKEN)
    logger.info("🚀 Бот запущен! Поддерживает Instagram, TikTok и Pinterest.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
