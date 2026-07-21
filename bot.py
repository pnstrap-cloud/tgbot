"""
Telegram-бот для скачивания видео и фото из Instagram, TikTok, YouTube Shorts и Pinterest.
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
    InputMediaVideo,
    Message,
)
from yt_dlp import YoutubeDL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== ТОКЕН ВШИТ В КОД =====
BOT_TOKEN = "ТВОЙ_НОВЫЙ_ТОКЕН_ОТ_BOTFATHER"
# ВНИМАНИЕ: не показывай этот токен никому!

# ===== ОПЦИОНАЛЬНО: сессия для Instagram =====
IG_SESSIONFILE = os.environ.get("IG_SESSIONFILE")
IG_USERNAME = os.environ.get("IG_USERNAME")

# ===== КОНСТАНТЫ =====
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
captions_store: dict[str, str] = {}


def make_caption_kb(caption_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Показать подпись", callback_data=f"cap:{caption_id}")]
        ]
    )


# ============ INSTAGRAM (instaloader) ============
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
    m = IG_URL_RE.search(url)
    if not m:
        return [], ""
    shortcode = m.group("shortcode")

    L = _build_instaloader()
    post = instaloader.Post.from_shortcode(L.context, shortcode)

    target = Path(out_dir) / shortcode
    target.mkdir(parents=True, exist_ok=True)
    L.dirname_pattern = str(target)
    L.filename_pattern = "{shortcode}_{mediaid}"

    L.download_post(post, target=shortcode)

    files = sorted(
        [p for p in target.rglob("*") if p.is_file() and p.suffix.lower() in (IMAGE_EXTS | VIDEO_EXTS)]
    )
    caption = (post.caption or "").strip()
    return files, caption


# ============ YT-DLP (остальные) ============
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
        [p for p in Path(out_dir).iterdir() if p.is_file() and p.suffix.lower() in (IMAGE_EXTS | VIDEO_EXTS)]
    )
    return files, info or {}


def extract_caption(info: dict) -> str:
    if not info:
        return ""
    for key in ("description", "title"):
        v = info.get(key)
        if v and isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def store_caption(text: str) -> str:
    cid = uuid.uuid4().hex[:12]
    captions_store[cid] = text or ""
    return cid


# ============ ОБРАБОТЧИКИ ============
@dp.message(CommandStart())
async def on_start(message: Message) -> None:
    await message.answer(
        "👋 Привет! Отправь ссылку из:\n"
        "• Instagram (пост, reels, IGTV)\n"
        "• TikTok\n"
        "• YouTube Shorts\n"
        "• Pinterest\n\n"
        "Я скачаю медиа и покажу подпись по кнопке!"
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

        ok_files = [p for p in files if p.stat().st_size <= TG_SIZE_LIMIT]

        if not ok_files:
            await status.edit_text("❌ Все файлы больше 50 МБ (лимит Telegram).")
            return

        await status.edit_text("📤 Отправляю...")

        try:
            images = [p for p in ok_files if p.suffix.lower() in IMAGE_EXTS]
            videos = [p for p in ok_files if p.suffix.lower() in VIDEO_EXTS]

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
                await message.reply("✅ Медиа отправлено.", reply_markup=kb)
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
                            await message.reply("✅ Фото отправлены.", reply_markup=kb)

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
        await cb.answer("Подпись недоступна.", show_alert=True)
        return
    await cb.answer()
    if text.strip():
        await cb.message.reply(text[:4000])
    else:
        await cb.message.reply("Подписи к этому медиа нет.")


@dp.message()
async def on_other(message: Message) -> None:
    await message.reply("❓ Отправь ссылку на Instagram, TikTok, YouTube Shorts или Pinterest.")


async def main() -> None:
    bot = Bot(BOT_TOKEN)
    logger.info("🚀 Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
