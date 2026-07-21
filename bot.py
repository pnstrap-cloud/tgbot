"""
Telegram-бот для скачивания видео и фото из Instagram, TikTok, YouTube Shorts и Pinterest.

Установка:
    pip install -r requirements.txt

Запуск:
    export BOT_TOKEN="ваш_токен_от_BotFather"
    python bot.py
"""

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

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Задай переменную окружения BOT_TOKEN")

# 50 МБ — лимит Telegram Bot API на отправку файлов
TG_SIZE_LIMIT = 50 * 1024 * 1024

URL_RE = re.compile(
    r"https?://(?:www\.)?"
    r"(?:instagram\.com/(?:p|reel|reels|tv)/[\w\-]+"
    r"|tiktok\.com/[^\s]+"
    r"|vm\.tiktok\.com/[^\s]+"
    r"|vt\.tiktok\.com/[^\s]+"
    r"|youtube\.com/shorts/[\w\-]+"
    r"|youtu\.be/[\w\-]+"
    r"|pinterest\.[\w.]+/pin/[\w\-]+"
    r"|pin\.it/[\w\-]+)",
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


def extract_info(url: str) -> dict:
    """Только метаданные, без скачивания."""
    ydl_opts = {"quiet": True, "no_warnings": True, "noplaylist": False, "skip_download": True}
    with YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)


def download_media(url: str, out_dir: str) -> tuple[list[Path], dict]:
    """
    Скачивает медиа. Возвращает (список путей, info dict).
    Для карусели/плейлиста скачивает все элементы.
    """
    ydl_opts = {
        "outtmpl": os.path.join(out_dir, "%(id)s_%(playlist_index)s.%(ext)s"),
        "format": "mp4/bestvideo*+bestaudio/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": False,
        "restrictfilenames": True,
        "ignoreerrors": True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    files = sorted(
        [p for p in Path(out_dir).iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS | VIDEO_EXTS]
    )
    return files, info or {}


async def download_url_to_file(session: aiohttp.ClientSession, url: str, dest: Path) -> Optional[Path]:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            if resp.status != 200:
                return None
            data = await resp.read()
            dest.write_bytes(data)
            return dest
    except Exception:
        logger.exception("Ошибка загрузки %s", url)
        return None


async def download_carousel_images(info: dict, out_dir: str) -> list[Path]:
    """Скачивает все фото из карусели Instagram по URL-ам из entries."""
    entries = info.get("entries") or []
    urls: list[str] = []
    for e in entries:
        if not e:
            continue
        u = e.get("url") or e.get("display_url")
        if not u and e.get("thumbnails"):
            thumbs = sorted(e["thumbnails"], key=lambda t: (t.get("width") or 0), reverse=True)
            if thumbs:
                u = thumbs[0].get("url")
        if u:
            urls.append(u)

    files: list[Path] = []
    async with aiohttp.ClientSession() as session:
        for i, u in enumerate(urls[:10]):
            dest = Path(out_dir) / f"img_{i}.jpg"
            r = await download_url_to_file(session, u, dest)
            if r:
                files.append(r)
    return files


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
        "Привет! Пришли ссылку из Instagram, TikTok, YouTube Shorts или Pinterest — "
        "скачаю видео/фото и отправлю обратно."
    )


@dp.message(F.text.regexp(URL_RE))
async def on_link(message: Message) -> None:
    match = URL_RE.search(message.text or "")
    if not match:
        return
    url = match.group(0)

    status = await message.reply("⏬ Скачиваю...")

    with tempfile.TemporaryDirectory() as tmp:
        info: dict = {}
        files: list[Path] = []
        try:
            files, info = await asyncio.to_thread(download_media, url, tmp)
        except Exception as e:
            logger.exception("Ошибка при скачивании")
            await status.edit_text(f"❌ Не удалось скачать: {e}")
            return

        if not files:
            try:
                if not info:
                    info = await asyncio.to_thread(extract_info, url)
                files = await download_carousel_images(info, tmp)
            except Exception:
                logger.exception("Ошибка получения карусели")

        if not files:
            await status.edit_text("❌ Не удалось получить медиа по этой ссылке.")
            return

        caption_text = extract_caption(info)
        caption_id = store_caption(caption_text)
        kb = make_caption_kb(caption_id)

        ok_files = []
        for p in files:
            if p.stat().st_size > TG_SIZE_LIMIT:
                logger.warning("Файл %s больше 50 МБ, пропуск", p)
                continue
            ok_files.append(p)

        if not ok_files:
            await status.edit_text("❌ Все файлы больше 50 МБ (лимит Telegram Bot API).")
            return

        await status.edit_text("📤 Отправляю...")

        try:
            images = [p for p in ok_files if p.suffix.lower() in IMAGE_EXTS]
            videos = [p for p in ok_files if p.suffix.lower() in VIDEO_EXTS]

            if images:
                if len(images) == 1:
                    await message.reply_photo(FSInputFile(images[0]), reply_markup=kb)
                else:
                    for chunk_start in range(0, len(images), 10):
                        chunk = images[chunk_start:chunk_start + 10]
                        media = [InputMediaPhoto(media=FSInputFile(p)) for p in chunk]
                        await message.reply_media_group(media)
                    await message.reply("Медиа отправлено.", reply_markup=kb)

            for i, v in enumerate(videos):
                markup = kb if (i == len(videos) - 1 and not images) else None
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
        chunk = text[:4000]
        await cb.message.reply(chunk)
    else:
        await cb.message.reply("Подписи к этому медиа нет.")


@dp.message()
async def on_other(message: Message) -> None:
    await message.reply("Пришли ссылку из Instagram, TikTok, YouTube Shorts или Pinterest.")


async def main() -> None:
    bot = Bot(BOT_TOKEN)
    logger.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
