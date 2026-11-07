# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Elinsrc

import html

import discord
from hydrogram.errors import MessageNotModified
from loguru import logger

from bridge.constants import DC_EMOJI_RE, TG_CAPTION_LIMIT, TG_TEXT_LIMIT
from bridge.db import LinkStore
from bridge.dc.formatter import DiscordFormatter
from bridge.dc.media import DiscordMedia
from bridge.models import MsgLink
from bridge.settings import Settings
from bridge.sync import DeletionSync
from bridge.tg.gateway import TelegramGateway


class DiscordBridge(discord.Client):
    def __init__(
        self,
        settings: Settings,
        store: LinkStore,
        telegram: TelegramGateway,
        media: DiscordMedia,
    ):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.messages = True
        intents.guilds = True
        super().__init__(intents=intents)
        self._cfg = settings
        self._store = store
        self._telegram = telegram
        self._media = media
        self._fmt = DiscordFormatter
        self._sync: DeletionSync | None = None

    def bind_sync(self, sync: DeletionSync) -> None:
        self._sync = sync

    async def on_ready(self) -> None:
        logger.info("Discord client ready as {} (id={})", self.user, self.user.id)
        channel = self.get_channel(self._cfg.discord_channel_id)
        if channel and not channel.permissions_for(channel.guild.me).manage_messages:
            logger.warning("Discord bot lacks 'Manage Messages' in the bridge channel: deletions from Telegram will not work")

    async def on_message(self, message: discord.Message) -> None:
        if message.channel.id != self._cfg.discord_channel_id:
            return
        if message.author.bot or message.webhook_id is not None:
            return
        try:
            await self._relay(message)
        except Exception as e:
            logger.error("Telegram send error: {!r}", e)

    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent) -> None:
        if payload.channel_id != self._cfg.discord_channel_id:
            return
        link = await self._store.get_by_dc(payload.message_id)
        if not link or link.origin != "dc" or not link.tg_ids:
            return

        dc_msg = getattr(payload, "message", None)
        if dc_msg is None:
            channel = self.get_channel(self._cfg.discord_channel_id)
            if not channel:
                return
            try:
                dc_msg = await channel.fetch_message(payload.message_id)
            except Exception:
                return

        text = self._fmt.prepare(dc_msg.clean_content or "")
        if text == link.last_text:
            return
        await self._store.update_last_text(link.dc_id, text)

        html_text, plain_text = self._fmt.build_texts(
            dc_msg.author.display_name, text,
            quote_html=link.reply_header,
            limit=TG_CAPTION_LIMIT if link.tg_has_media else TG_TEXT_LIMIT,
        )
        primary = link.tg_ids[0]

        try:
            if link.tg_has_media:
                await self._telegram.edit_caption(primary, html_text, plain_text)
            else:
                await self._telegram.edit_text(primary, html_text, plain_text)
            logger.info("DC edit -> TG | dc={} tg={}", payload.message_id, primary)
        except MessageNotModified:
            pass
        except Exception as e:
            logger.error("Telegram edit error: {!r}", e)

    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        if payload.channel_id == self._cfg.discord_channel_id:
            await self._sync.discord_deleted([payload.message_id])

    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent) -> None:
        if payload.channel_id == self._cfg.discord_channel_id:
            await self._sync.discord_deleted(list(payload.message_ids))

    async def _relay(self, message: discord.Message) -> None:
        snapshots = getattr(message, "message_snapshots", None) or []
        source = snapshots[0] if snapshots else message
        author_name = message.author.display_name
        original_text = self._fmt.prepare((source.content if snapshots else message.clean_content) or "")
        emoji_list = DC_EMOJI_RE.findall(original_text)

        reply_to: int | None = None
        quote = ""
        if snapshots:
            quote = self._fmt.forward_quote(self._forward_author(message))
            embeds = list(source.embeds)
        else:
            reply_to, quote = await self._resolve_reply(message)
            embeds = await self._media.resolve_embeds(message)

        collected = await self._media.collect(source, embeds, original_text)
        items = collected.items
        text = self._media.strip_urls(original_text, collected.consumed_urls)
        emoji_as_main = False

        if not items:
            emojis = self._media.emoji_only(text)
            if emojis:
                items = await self._media.emoji_items(emojis)
                if items:
                    text = ""
                    emoji_as_main = True
        if collected.notes:
            text = "\n".join(filter(None, [text, *collected.notes]))

        if not items and not text:
            return

        html_text, plain_text = self._fmt.build_texts(
            author_name, text, quote_html=quote,
            limit=TG_CAPTION_LIMIT if items else TG_TEXT_LIMIT,
        )

        sent_ids: list[int] = []
        if not items:
            sent = await self._telegram.send_text(html_text, plain_text, reply_to)
            sent_ids.append(sent.id)
        else:
            for idx, item in enumerate(items):
                sent = await self._telegram.send_media(item, idx, reply_to, html_text, plain_text)
                sent_ids.append(sent.id)

        if self._cfg.emoji_as_images and emoji_list and not emoji_as_main and sent_ids:
            unique = list({eid: (a, n, eid) for a, n, eid in emoji_list}.values())
            for item in await self._media.emoji_items(unique[: self._cfg.emoji_image_limit]):
                try:
                    extra = await self._telegram.send_media(item, 0, sent_ids[0], None, None)
                    sent_ids.append(extra.id)
                except Exception as e:
                    logger.warning("Emoji image send failed: {!r}", e)

        if sent_ids and message.guild:
            await self._store.save(MsgLink(
                dc_id=message.id,
                tg_ids=sent_ids,
                guild_id=message.guild.id,
                origin="dc",
                tg_has_media=bool(items),
                reply_header=quote,
                last_text=original_text,
            ))
            logger.info(
                "DC -> TG | {} | dc={} tg={} media={}",
                author_name, message.id, sent_ids, len(items),
            )

    async def _resolve_reply(self, message: discord.Message) -> tuple[int | None, str]:
        if not (message.reference and message.reference.message_id):
            return None, ""

        ref_link = await self._store.get_by_dc(message.reference.message_id)
        if ref_link and ref_link.tg_ids:
            return ref_link.tg_ids[0], ""

        resolved = message.reference.resolved
        if isinstance(resolved, discord.Message):
            author = html.escape(resolved.author.display_name)
            snippet = self._fmt.quote_snippet(resolved.clean_content or "[Media]")
            return None, f"<blockquote>↪️ {author}: {snippet}</blockquote>\n"
        return None, ""

    @staticmethod
    def _forward_author(message: discord.Message) -> str | None:
        resolved = message.reference.resolved if message.reference else None
        if isinstance(resolved, discord.Message):
            return resolved.author.display_name
        return None
