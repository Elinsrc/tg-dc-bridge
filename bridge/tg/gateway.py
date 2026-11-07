# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Elinsrc

from hydrogram import Client
from hydrogram.enums import ParseMode
from hydrogram.errors import BadRequest
from hydrogram.types import Message
from loguru import logger

from bridge.models import OutMedia


class TelegramGateway:
    def __init__(self, client: Client, chat_id: int):
        self.client = client
        self.chat_id = chat_id

    async def send_text(self, html_text: str, plain_text: str, reply_to: int | None = None) -> Message:
        return await self._call(
            self.client.send_message, self.chat_id,
            text_kw="text", html_text=html_text, plain_text=plain_text,
            reply_to_message_id=reply_to,
        )

    async def send_media(
        self, item: OutMedia, index: int, reply_to: int | None,
        html_caption: str | None, plain_caption: str | None,
    ) -> Message:
        senders = {
            "photo": self.client.send_photo,
            "video": self.client.send_video,
            "animation": self.client.send_animation,
            "audio": self.client.send_audio,
            "voice": self.client.send_voice,
            "document": self.client.send_document,
        }
        kwargs: dict = {"reply_to_message_id": reply_to if index == 0 else None}
        if item.kind in ("photo", "video", "animation") and item.spoiler:
            kwargs["has_spoiler"] = True
        if item.kind == "voice" and item.duration:
            kwargs["duration"] = item.duration

        cap_html = html_caption if index == 0 else None
        cap_plain = plain_caption if index == 0 else None

        try:
            return await self._call(
                senders[item.kind], self.chat_id, item.buf,
                text_kw="caption", html_text=cap_html, plain_text=cap_plain, **kwargs,
            )
        except BadRequest as e:
            if item.kind == "document":
                raise
            logger.warning("send_{} failed ({}), retrying as document", item.kind, e)
            item.buf.seek(0)
            kwargs.pop("has_spoiler", None)
            kwargs.pop("duration", None)
            return await self._call(
                self.client.send_document, self.chat_id, item.buf,
                text_kw="caption", html_text=cap_html, plain_text=cap_plain, **kwargs,
            )

    async def edit_text(self, message_id: int, html_text: str, plain_text: str) -> Message:
        return await self._call(
            self.client.edit_message_text, self.chat_id, message_id,
            text_kw="text", html_text=html_text, plain_text=plain_text,
        )

    async def edit_caption(self, message_id: int, html_text: str, plain_text: str) -> Message:
        return await self._call(
            self.client.edit_message_caption, self.chat_id, message_id,
            text_kw="caption", html_text=html_text, plain_text=plain_text,
        )

    async def can_delete(self) -> bool:
        try:
            member = await self.client.get_chat_member(self.chat_id, "me")
        except Exception as e:
            logger.warning("Cannot check Telegram bot permissions: {!r}", e)
            return True
        privileges = getattr(member, "privileges", None)
        return member.status.name == "OWNER" or bool(privileges and privileges.can_delete_messages)

    async def delete(self, message_ids: list[int]) -> None:
        await self.client.delete_messages(self.chat_id, message_ids)

    @staticmethod
    async def _call(func, *args, text_kw: str, html_text: str | None, plain_text: str | None, **kwargs):
        if html_text is None:
            return await func(*args, **kwargs)
        try:
            return await func(*args, **{text_kw: html_text}, parse_mode=ParseMode.HTML, **kwargs)
        except BadRequest as e:
            msg = str(e).lower()
            if "entit" not in msg and "parse" not in msg:
                raise
            logger.warning("Telegram rejected HTML, retrying without formatting: {}", e)
            for a in args:
                if hasattr(a, "seek"):
                    a.seek(0)
            return await func(*args, **{text_kw: plain_text}, parse_mode=ParseMode.DISABLED, **kwargs)
