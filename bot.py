"""
Telegram-бот для скачивания видео и фото из Instagram, TikTok, YouTube Shorts и Pinterest.

Instagram скачивается через instaloader (поддерживает посты, reels, IGTV, карусели,
одиночные фото и видео). Для остальных источников используется yt-dlp.

Установка:
    pip install -r requirements.txt

Запуск:
    export BOT_TOKEN="ваш_токен_от_BotFather"
    # опционально, для приватных/ограниченных постов Instagram:
    # export IG_SESSIONFILE="/path/to/instaloader-session-USERNAME"
    # export IG_USERNAME="ваш_ig_логин"
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
import instaloader
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    BOT_TOKEN = "1850605284:AAFHm0BnbGsgIpw1rEFbsChjCf2rywzlphc"

from yt_dlp import YoutubeDL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Задай переменную окружения BOT_TOKEN")

IG_SESSIONFILE = os.environ.get("IG_SESSIONFILE")
IG_USERNAME = os.environ.get("IG_USERNAME")

# 50 МБ — лимит Telegram Bot API на отправку файлов
TG_SIZE_LIMIT = 50 * 1024 * 1024

IG_URL_RE = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:p|reel|reels|tv)/(?P<shortcode>[\w\-]+)",
    re.IGNORECASE,
)

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


# ---------------- Instagram (instaloader) ----------------

def _build_instaloader() -> instaloader.Instaloader:
    L = instaloader.Instaloader(
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        post_metadata_txt_pattern="",
        quiet=True,
    )
    if IG_SESSIONFILE and IG_USERNAME:
        try:
            L.load_session_from_file(IG_USERNAME, IG_SESSIONFILE)
            logger.info("Instagram: сессия загружена для %s", IG_USERNAME)
        except Exception:
            logger.exception("Не удалось загрузить сессию Instagram, работаем анонимно")
    return L


def download_instagram(url: str, out_dir: str) -> tuple[list[Path], str]:
    """Скачивает пост/reel/карусель через instaloader. Возвращает (файлы, подпись)."""
    m = IG_URL_RE.search(url)
    if not m:
        return [], ""
    shortcode = m.group("shortcode")

    L = _build_instaloader()
    post = instaloader.Post.from_shortcode(L.context, shortcode)

    target = Path(out_dir) / shortcode
    target.mkdir(parents=True, exist_ok=True)
    # instaloader пишет в поддиректорию target относительно текущей dirname_pattern
    L.dirname_pattern = str(target)
    L.filename_pattern = "{shortcode}_{mediaid}"

    L.download_post(post, target=shortcode)

    files = sorted(
        [
            p for p in target.rglob("*")
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS | VIDEO_EXTS
        ]
    )
    caption = (post.caption or "").strip()
    return files, caption


# ---------------- yt-dlp (остальные источники) ----------------

def extract_info(url: str) -> dict:
    ydl_opts = {"quiet": True, "no_warnings": True, "noplaylist": False, "skip_download": True}
    with YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)


def download_media(url: str, out_dir: str) -> tuple[list[Path], dict]:
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


def extract_caption(info: dict) -> str:
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
        files: list[Path] = []
        caption_text = ""

        is_instagram = bool(IG_URL_RE.search(url))

        try:
            if is_instagram:
                files, caption_text = await asyncio.to_thread(download_instagram, url, tmp)
            else:
                files, info = await asyncio.to_thread(download_media, url, tmp)
                caption_text = extract_caption(info)
        except Exception as e:
            logger.exception("Ошибка при скачивании")
            await status.edit_text(f"❌ Не удалось скачать: {e}")
            return

        if not files:
            await status.edit_text("❌ Не удалось получить медиа по этой ссылке.")
            return

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
            await status.edit_text("❌ Все файлы больше 50 МБ (лимит Telegram Bot API).")
            return

        await status.edit_text("📤 Отправляю...")

        try:
            images = [p for p in ok_files if p.suffix.lower() in IMAGE_EXTS]
            videos = [p for p in ok_files if p.suffix.lower() in VIDEO_EXTS]

            # Instagram-карусель может смешивать фото и видео — отправим одним альбомом
            if is_instagram and len(ok_files) > 1:
                for chunk_start in range(0, len(ok_files), 10):
                    chunk = ok_files[chunk_start:chunk_start + 10]
                    media = []
                    for p in chunk:
                        if p.suffix.lower() in IMAGE_EXTS:
                            media.append(InputMediaPhoto(media=FSInputFile(p)))
                        else:
                            media.append(InputMediaVideo(media=FSInputFile(p)))
                    await message.reply_media_group(media)
                await message.reply("Медиа отправлено.", reply_markup=kb)
            else:
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
