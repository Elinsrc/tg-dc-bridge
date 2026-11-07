# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Elinsrc

import asyncio
import io
import re
from pathlib import Path
from urllib.parse import urlparse

import discord
from loguru import logger

from bridge.constants import ATTACHMENT_SPOILER_FLAG, DC_EMOJI_RE, DC_GIF_LINK_RE, TG_MAX_FILE
from bridge.http import HttpClient
from bridge.models import DcCollected, OutMedia


class DiscordMedia:
    EMBED_WAIT = 1.5
    EMOJI_ONLY_LIMIT = 5

    def __init__(self, http: HttpClient):
        self.http = http

    @staticmethod
    def make_buf(data: bytes, name: str) -> io.BytesIO:
        buf = io.BytesIO(data)
        buf.name = name
        return buf

    @staticmethod
    def is_spoiler(att) -> bool:
        if att.filename.startswith("SPOILER_"):
            return True
        flags = getattr(att, "flags", None)
        value = getattr(flags, "value", flags)
        try:
            return bool(int(value or 0) & ATTACHMENT_SPOILER_FLAG)
        except (TypeError, ValueError):
            return False

    @staticmethod
    def attachment_kind(content_type: str, filename: str, is_voice: bool) -> str:
        if is_voice:
            return "voice"
        if content_type == "image/gif" or filename.lower().endswith(".gif"):
            return "animation"
        if content_type in ("image/jpeg", "image/png", "image/webp"):
            return "photo"
        if content_type.startswith("video/"):
            return "video"
        if content_type.startswith("audio/"):
            return "audio"
        return "document"

    @staticmethod
    def gif_embed_url(embed) -> str | None:
        if embed.type == "gifv":
            return getattr(embed.video, "url", None)
        if embed.type == "image" and embed.url and urlparse(embed.url).path.lower().endswith(".gif"):
            return embed.url
        return None

    @staticmethod
    def is_spoilered(text: str, url: str) -> bool:
        pattern = r"\|\|(?:(?!\|\|).)*?" + re.escape(url) + r"(?:(?!\|\|).)*?\|\|"
        return bool(re.search(pattern, text, re.S))

    @staticmethod
    def strip_urls(text: str, urls: list[str]) -> str:
        if not urls:
            return text.strip()
        for url in urls:
            text = text.replace(f"<{url}>", "").replace(url, "")
        return re.sub(r"\|\|\s*\|\|", "", text).strip()

    @staticmethod
    def emoji_only(text: str) -> list[tuple[str, str, str]] | None:
        found = DC_EMOJI_RE.findall(text)
        if found and not DC_EMOJI_RE.sub("", text).strip() and len(found) <= DiscordMedia.EMOJI_ONLY_LIMIT:
            return found
        return None

    async def resolve_embeds(self, message: discord.Message) -> list[discord.Embed]:
        if message.embeds or not DC_GIF_LINK_RE.search(message.content or ""):
            return message.embeds
        await asyncio.sleep(self.EMBED_WAIT)
        try:
            fresh = await message.channel.fetch_message(message.id)
        except Exception:
            return []
        return fresh.embeds

    async def collect(
        self, source, embeds: list[discord.Embed] | None = None, text: str = "",
    ) -> DcCollected:
        result = DcCollected()
        await self._attachments(source, result)
        await self._stickers(source, result)
        await self._gif_embeds(source.embeds if embeds is None else embeds, result, text)
        return result

    async def emoji_items(self, emojis: list[tuple[str, str, str]]) -> list[OutMedia]:
        items: list[OutMedia] = []
        for animated, name, eid in emojis:
            ext = "gif" if animated else "png"
            data = await self.http.fetch(f"https://cdn.discordapp.com/emojis/{eid}.{ext}?size=128&quality=lossless")
            if data:
                items.append(OutMedia(
                    kind="animation" if animated else "photo",
                    buf=self.make_buf(data, f"{name}.{ext}"),
                    filename=f"{name}.{ext}",
                ))
        return items

    async def _attachments(self, source, result: DcCollected) -> None:
        for att in source.attachments:
            if att.size > TG_MAX_FILE:
                result.notes.append(f"[{att.filename}: file is too large]")
                continue
            try:
                data = await att.read()
            except Exception as e:
                logger.warning("Attachment read failed: {!r}", e)
                result.notes.append(f"[{att.filename}: download failed]")
                continue

            content_type = (att.content_type or "").split(";")[0].strip().lower()
            is_voice = bool(getattr(att, "is_voice_message", None) and att.is_voice_message())
            duration = getattr(att, "duration", None)
            name = att.filename.removeprefix("SPOILER_")
            spoiler = self.is_spoiler(att)

            result.items.append(OutMedia(
                kind=self.attachment_kind(content_type, att.filename, is_voice),
                buf=self.make_buf(data, name),
                filename=name,
                spoiler=spoiler,
                duration=int(duration) if duration else None,
            ))

    async def _stickers(self, source, result: DcCollected) -> None:
        for st in getattr(source, "stickers", None) or []:
            fmt = st.format.name
            if fmt == "lottie":
                result.notes.append(f"[Sticker: {st.name}]")
                continue
            data = await self.http.fetch(st.url)
            if not data:
                result.notes.append(f"[Sticker: {st.name}]")
                continue
            ext = "gif" if fmt == "gif" else "png"
            result.items.append(OutMedia(
                kind="animation" if fmt == "gif" else "photo",
                buf=self.make_buf(data, f"{st.name}.{ext}"),
                filename=f"{st.name}.{ext}",
            ))

    async def _gif_embeds(self, embeds: list[discord.Embed], result: DcCollected, text: str) -> None:
        for embed in embeds:
            url = self.gif_embed_url(embed)
            if not url:
                continue
            data = await self.http.fetch(url)
            if not data or len(data) > TG_MAX_FILE:
                continue
            ext = Path(urlparse(url).path).suffix.lower() or ".mp4"
            name = f"animation{ext}"
            result.items.append(OutMedia(
                kind="animation", buf=self.make_buf(data, name), filename=name,
                spoiler=bool(embed.url) and self.is_spoilered(text, embed.url),
            ))
            if embed.url:
                result.consumed_urls.append(embed.url)
