# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Elinsrc

import io
import re
from collections import OrderedDict
from pathlib import Path

import discord
from hydrogram import Client
from hydrogram.types import Message
from loguru import logger

from bridge.constants import MAX_DISCORD_FILES, STICKER_CACHE_BYTES
from bridge.gif import GifConverter
from bridge.models import TgCollected
from bridge.settings import Settings
from bridge.tg.formatter import TelegramFormatter


class TelegramMedia:
    def __init__(self, client: Client, gif: GifConverter, settings: Settings):
        self.client = client
        self.gif = gif
        self.settings = settings
        self._stickers: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
        self._cache_bytes = 0

    @staticmethod
    def safe_filename(name: str) -> str:
        return re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "file.bin"

    @staticmethod
    def has_spoiler(message: Message) -> bool:
        names = ("has_media_spoiler", "media_spoiler", "has_spoiler")
        return any(bool(getattr(message, name, False)) for name in names)

    @staticmethod
    def descriptor(message: Message) -> tuple[object, str] | None:
        if message.photo:
            return message.photo, "photo.jpg"
        if message.video:
            return message.video, message.video.file_name or "video.mp4"
        if message.animation:
            return message.animation, message.animation.file_name or "animation.mp4"
        if message.video_note:
            return message.video_note, "video_note.mp4"
        if message.voice:
            return message.voice, "voice.ogg"
        if message.audio:
            a = message.audio
            if a.file_name:
                name = a.file_name
            elif a.performer and a.title:
                name = f"{a.performer} - {a.title}.mp3"
            else:
                name = "audio.mp3"
            return a, name
        if message.document:
            return message.document, message.document.file_name or "file.bin"
        return None

    async def sticker_file(self, sticker, idx: int = 0) -> discord.File | None:
        key = sticker.file_unique_id
        cached = self._stickers.get(key)
        if cached is None:
            try:
                cached = await self._load_sticker(sticker)
            except Exception as e:
                logger.warning("Sticker download failed: {!r}", e)
                return None
            if cached is None:
                return None
            self._remember(key, cached)
        data, ext = cached
        return discord.File(io.BytesIO(data), filename=f"sticker_{idx}.{ext}")

    async def _download(self, file_id: str) -> bytes | None:
        buf = await self.client.download_media(file_id, in_memory=True)
        return bytes(buf.getbuffer()) if buf else None

    async def _load_sticker(self, sticker) -> tuple[bytes, str] | None:
        if sticker.is_animated:
            data = await self._download(sticker.file_id)
            if data:
                gif = await self.gif.tgs_to_gif(data)
                if gif:
                    return gif, "gif"
            if sticker.thumbs:
                thumb = await self._download(sticker.thumbs[0].file_id)
                if thumb:
                    return thumb, "webp"
            return None

        data = await self._download(sticker.file_id)
        if not data:
            return None
        if sticker.is_video:
            gif = await self.gif.webm_to_gif(data)
            return (gif, "gif") if gif else (data, "webm")
        return data, "webp"

    def _remember(self, key: str, value: tuple[bytes, str]) -> None:
        self._stickers[key] = value
        self._cache_bytes += len(value[0])
        while self._cache_bytes > STICKER_CACHE_BYTES and len(self._stickers) > 1:
            _, evicted = self._stickers.popitem(last=False)
            self._cache_bytes -= len(evicted[0])

    async def emoji_files(self, emoji_ids: list[int], limit: int) -> list[discord.File]:
        try:
            stickers = await self.client.get_custom_emoji_stickers(emoji_ids[:limit])
        except Exception as e:
            logger.warning("Custom emoji fetch failed: {!r}", e)
            return []
        files: list[discord.File] = []
        for i, sticker in enumerate(stickers):
            file = await self.sticker_file(sticker, i)
            if file:
                files.append(file)
        return files

    async def collect(self, message: Message) -> TgCollected:
        result = TgCollected()

        if message.sticker:
            file = await self.sticker_file(message.sticker)
            if file:
                result.files.append(file)
            else:
                result.notes.append(f"[Sticker {message.sticker.emoji or ''}]".replace(" ]", "]"))
            return result

        emoji_files: list[discord.File] = []
        emoji_ids = TelegramFormatter.custom_emoji_ids(message)
        if emoji_ids and self.settings.emoji_as_images:
            only_emoji = TelegramFormatter.is_only_custom_emoji(message)
            limit = MAX_DISCORD_FILES if only_emoji else self.settings.emoji_image_limit
            emoji_files = await self.emoji_files(emoji_ids, limit)
            if emoji_files and only_emoji:
                result.files = emoji_files
                result.drop_text = True
                return result

        desc = self.descriptor(message)
        if desc:
            media, name = desc
            size = getattr(media, "file_size", 0) or 0
            if size > self.settings.max_discord_file:
                result.notes.append(f"[{name}: file is too large ({size / 1048576:.1f} MB)]")
            else:
                buf = await self.client.download_media(message, in_memory=True)
                if buf:
                    result.files.append(await self._media_file(message, buf, name))
                else:
                    result.notes.append(f"[{name}: download failed]")

        room = max(0, MAX_DISCORD_FILES - len(result.files))
        result.files.extend(emoji_files[:room])
        return result

    async def _media_file(self, message: Message, buf: io.BytesIO, name: str) -> discord.File:
        spoiler = self.has_spoiler(message)
        animation = message.animation
        if animation and getattr(animation, "mime_type", None) != "image/gif":
            gif_bytes = await self.gif.video_to_gif(buf.getvalue())
            if gif_bytes:
                return discord.File(
                    io.BytesIO(gif_bytes), filename=f"{Path(name).stem}.gif", spoiler=spoiler,
                )
        buf.seek(0)
        return discord.File(buf, filename=self.safe_filename(name), spoiler=spoiler)
