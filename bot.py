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

BOT_TOKEN = "1850605284:AAFHm0BnbGsgIpw1rEFbsChjCf2rywzlphc"

# ===== КОНСТАНТЫ =====
TG_SIZE_LIMIT = 50 * 1024 * 1024  # 50 МБ — лимит Telegram

# ===== РЕГУЛЯРНЫЕ ВЫРАЖЕНИЯ ДЛЯ ССЫЛОК =====
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

# ===== ИНИЦИАЛИЗАЦИЯ =====
dp = Dispatcher()

# Хранилище подписей (в памяти, при перезапуске очищается)
captions_store: dict[str, str] = {}


# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
def make_caption_kb(caption_id: str) -> InlineKeyboardMarkup:
    """Создаёт кнопку для показа подписи."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Показать подпись", callback_data=f"cap:{caption_id}")]
        ]
    )


def extract_info(url: str) -> dict:
    """Получает метаданные без скачивания."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": False,
        "skip_download": True,
        "ignoreerrors": True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        try:
            return ydl.extract_info(url, download=False) or {}
        except Exception as e:
            logger.error(f"Ошибка получения info: {e}")
            return {}


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
        "extract_flat": False,
    }
    info = {}
    files = []
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True) or {}
        files = sorted(
            [p for p in Path(out_dir).iterdir() if p.is_file() and p.suffix.lower() in (IMAGE_EXTS | VIDEO_EXTS)]
        )
    except Exception as e:
        logger.error(f"Ошибка скачивания: {e}")
    return files, info


async def download_url_to_file(session: aiohttp.ClientSession, url: str, dest: Path) -> Optional[Path]:
    """Скачивает файл по прямой ссылке."""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            if resp.status != 200:
                return None
            data = await resp.read()
            dest.write_bytes(data)
            return dest
    except Exception as e:
        logger.error(f"Ошибка загрузки {url}: {e}")
        return None


async def download_carousel_images(info: dict, out_dir: str) -> list[Path]:
    """Скачивает все фото из карусели Instagram."""
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
    """Извлекает описание/подпись из метаданных."""
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
    """Сохраняет подпись и возвращает ID."""
    cid = uuid.uuid4().hex[:12]
    captions_store[cid] = text or ""
    return cid


# ===== ОБРАБОТЧИКИ КОМАНД =====
@dp.message(CommandStart())
async def on_start(message: Message) -> None:
    await message.answer(
        "👋 Привет! Я умею скачивать:\n"
        "📸 Фото из Instagram и Pinterest\n"
        "🎬 Видео из Instagram, TikTok, YouTube Shorts и Pinterest\n\n"
        "Просто отправь мне ссылку — и я всё сделаю!"
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

        # Если ничего не скачалось — пробуем карусель
        if not files:
            try:
                if not info:
                    info = await asyncio.to_thread(extract_info, url)
                files = await download_carousel_images(info, tmp)
            except Exception as e:
                logger.exception("Ошибка получения карусели")
                await status.edit_text(f"❌ Не удалось обработать ссылку: {e}")
                return

        if not files:
            await status.edit_text("❌ Не удалось получить медиа по этой ссылке.")
            return

        caption_text = extract_caption(info)
        caption_id = store_caption(caption_text)
        kb = make_caption_kb(caption_id)

        # Фильтруем файлы по размеру
        ok_files = []
        for p in files:
            if p.stat().st_size > TG_SIZE_LIMIT:
                logger.warning(f"Файл {p} больше 50 МБ, пропуск")
                continue
            ok_files.append(p)

        if not ok_files:
            await status.edit_text("❌ Все файлы больше 50 МБ (лимит Telegram Bot API).")
            return

        await status.edit_text("📤 Отправляю...")

        try:
            images = [p for p in ok_files if p.suffix.lower() in IMAGE_EXTS]
            videos = [p for p in ok_files if p.suffix.lower() in VIDEO_EXTS]

            # Отправка изображений
            if images:
                if len(images) == 1:
                    await message.reply_photo(FSInputFile(images[0]), reply_markup=kb)
                else:
                    # Отправляем пачками по 10 (лимит Telegram)
                    for chunk_start in range(0, len(images), 10):
                        chunk = images[chunk_start:chunk_start + 10]
                        media = [InputMediaPhoto(media=FSInputFile(p)) for p in chunk]
                        await message.reply_media_group(media)
                    await message.reply("📸 Фото отправлены.", reply_markup=kb)

            # Отправка видео
            for i, v in enumerate(videos):
                markup = kb if (i == len(videos) - 1 and not images) else None
                try:
                    await message.reply_video(FSInputFile(v), reply_markup=markup)
                except Exception as e:
                    logger.error(f"Ошибка отправки видео: {e}")
                    await message.reply(f"❌ Не удалось отправить видео: {e}")

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
        # Telegram ограничение на длину сообщения — 4096 символов
        chunk = text[:4000]
        await cb.message.reply(f"📝 {chunk}")
    else:
        await cb.message.reply("Подписи к этому медиа нет.")


@dp.message()
async def on_other(message: Message) -> None:
    await message.reply(
        "❓ Я не понял. Отправь ссылку из:\n"
        "• Instagram (p/reel/reels/tv)\n"
        "• TikTok\n"
        "• YouTube Shorts\n"
        "• Pinterest"
    )


# ===== ЗАПУСК =====
async def main() -> None:
    bot = Bot(BOT_TOKEN)
    logger.info("🚀 Бот запущен и готов к работе!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем.")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
