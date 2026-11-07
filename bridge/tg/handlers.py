# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Elinsrc

import discord
from hydrogram import Client, filters
from hydrogram.handlers import DeletedMessagesHandler, EditedMessageHandler, MessageHandler
from hydrogram.types import Message
from loguru import logger

from bridge.constants import DC_TEXT_LIMIT, FORWARD_LABEL
from bridge.db import LinkStore
from bridge.dc.gateway import DiscordGateway
from bridge.models import MsgLink
from bridge.settings import Settings
from bridge.sync import DeletionSync
from bridge.tg.formatter import TelegramFormatter
from bridge.tg.media import TelegramMedia


class TelegramHandlers:
    def __init__(
        self,
        client: Client,
        settings: Settings,
        store: LinkStore,
        discord_gateway: DiscordGateway,
        sync: DeletionSync,
        media: TelegramMedia,
    ):
        self.client = client
        self.settings = settings
        self.store = store
        self.discord = discord_gateway
        self.sync = sync
        self.media = media
        self.fmt = TelegramFormatter

    def register(self) -> None:
        chat = filters.chat(self.settings.tg_chat_id)
        self.client.add_handler(MessageHandler(self.on_message, chat))
        self.client.add_handler(EditedMessageHandler(self.on_edit, chat))
        self.client.add_handler(DeletedMessagesHandler(self.on_delete))

    async def on_message(self, client: Client, message: Message) -> None:
        if message.from_user and message.from_user.is_bot:
            return

        sender_name, _ = self.fmt.sender_info(message)
        avatar_url = self.fmt.avatar_url(message)

        header = await self._reply_header(message) + self._forward_header(message)
        text = self.fmt.text_for_discord(message) or self.fmt.special_text(message)
        body = text

        collected = await self.media.collect(message)
        if collected.drop_text:
            body = ""
        if collected.notes:
            body = "\n".join(filter(None, [body, *collected.notes]))

        content = f"{header}{body}".strip()
        if not content and not collected.files:
            return

        try:
            dc_msg = await self.discord.send_as_user(
                content=content[:DC_TEXT_LIMIT] if content else discord.utils.MISSING,
                username=sender_name,
                avatar_url=avatar_url,
                files=collected.files or discord.utils.MISSING,
            )
            if dc_msg:
                await self.store.save(MsgLink(
                    dc_id=dc_msg.id,
                    tg_ids=[message.id],
                    guild_id=self.settings.discord_guild_id,
                    origin="tg",
                    tg_has_media=bool(collected.files),
                    reply_header=header,
                    last_text=text,
                ))
                logger.info(
                    "TG -> DC | {} | tg={} dc={} files={}",
                    sender_name, message.id, dc_msg.id, len(collected.files),
                )
        except Exception as e:
            logger.error("Webhook send error: {!r}", e)

    async def on_edit(self, client: Client, message: Message) -> None:
        link = await self.store.get_by_tg(message.id)
        if not link or link.origin != "tg":
            return

        new_body = self.fmt.text_for_discord(message)
        if new_body == link.last_text:
            return
        await self.store.update_last_text(link.dc_id, new_body)

        content = f"{link.reply_header}{new_body}".strip()
        try:
            await self.discord.edit_as_user(link.dc_id, content[:DC_TEXT_LIMIT] if content else None)
            logger.info("TG edit -> DC | tg={} dc={}", message.id, link.dc_id)
        except Exception as e:
            logger.error("Webhook edit error: {!r}", e)

    async def on_delete(self, client: Client, messages: list[Message]) -> None:
        ids = [msg.id for msg in messages if not (msg.chat and msg.chat.id != self.settings.tg_chat_id)]
        if ids:
            await self.sync.telegram_deleted(ids)

    async def _reply_header(self, message: Message) -> str:
        reply = message.reply_to_message
        if not reply:
            return ""

        entities = reply.entities if reply.text else reply.caption_entities
        raw = self.fmt.spoiler_markup(str(reply.text or reply.caption or ""), entities)

        if reply.from_user and reply.from_user.is_self:
            author = raw.split(":", 1)[0].strip() if ":" in raw else "Discord"
            snippet = raw.split(":", 1)[1].strip() if ":" in raw else raw
        else:
            author, _ = self.fmt.sender_info(reply)
            snippet = raw or "[Media]"

        snippet = snippet.replace("\n", " ").strip()
        if len(snippet) > 70:
            snippet = snippet[:67] + "..."
        if snippet.count("||") % 2:
            snippet += "||"
        if not snippet:
            snippet = "[Media]"

        link = await self.store.get_by_tg(reply.id)
        if link:
            url = (
                f"https://discord.com/channels/{link.guild_id}/"
                f"{self.settings.discord_channel_id}/{link.dc_id}"
            )
            return f"> **↪️ [Reply]({url}) {author}:** {snippet}\n"
        return f"> **↪️ Reply {author}:** {snippet}\n"

    def _forward_header(self, message: Message) -> str:
        name = self.fmt.forward_name(message)
        if not name:
            return ""
        return f"> **↪️ {FORWARD_LABEL} {discord.utils.escape_markdown(name)}**\n"
