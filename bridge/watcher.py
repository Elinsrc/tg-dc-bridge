# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Elinsrc

import asyncio

import discord
from hydrogram import Client
from loguru import logger

from bridge.constants import (
    DELETE_CHECK_CHUNK,
    DELETE_CHECK_GUARD,
    DELETE_CHECK_HISTORY,
    DELETE_CHECK_LIMIT,
)
from bridge.db import LinkStore
from bridge.models import MsgLink
from bridge.settings import Settings
from bridge.sync import DeletionSync


class DeletionWatcher:
    def __init__(
        self,
        settings: Settings,
        store: LinkStore,
        tg_client: Client,
        dc_client: discord.Client,
        sync: DeletionSync,
    ):
        self.settings = settings
        self.store = store
        self.tg_client = tg_client
        self.dc_client = dc_client
        self.sync = sync

    async def run(self) -> None:
        await self.dc_client.wait_until_ready()
        while True:
            try:
                await self.check()
            except Exception as e:
                logger.warning("Deletion check failed: {!r}", e)
            await asyncio.sleep(self.settings.delete_check_interval)

    async def check(self) -> None:
        links = await self.store.recent(DELETE_CHECK_LIMIT)
        if not links:
            return

        missing_tg = await self._missing_in_telegram(links)
        if missing_tg:
            logger.info("Deletion check: Telegram messages gone {}", missing_tg)
            await self.sync.telegram_deleted(missing_tg)
            links = await self.store.recent(DELETE_CHECK_LIMIT)

        missing_dc = await self._missing_in_discord(links)
        if missing_dc:
            logger.info("Deletion check: Discord messages gone {}", missing_dc)
            await self.sync.discord_deleted(missing_dc)

    async def _missing_in_telegram(self, links: list[MsgLink]) -> list[int]:
        ids = [tid for link in links for tid in link.tg_ids]
        missing: list[int] = []
        for i in range(0, len(ids), DELETE_CHECK_CHUNK):
            chunk = ids[i:i + DELETE_CHECK_CHUNK]
            try:
                messages = await self.tg_client.get_messages(self.settings.tg_chat_id, chunk)
            except Exception as e:
                logger.warning("Telegram existence check failed: {!r}", e)
                return []
            gone = [m.id for m in messages if getattr(m, "empty", False)]
            if len(chunk) > DELETE_CHECK_GUARD and len(gone) == len(chunk):
                logger.warning("Telegram existence check reports everything deleted, ignoring")
                return []
            missing.extend(gone)
        return missing

    async def _missing_in_discord(self, links: list[MsgLink]) -> list[int]:
        channel = self.dc_client.get_channel(self.settings.discord_channel_id)
        if not channel or not links:
            return []
        try:
            fetched = [m.id async for m in channel.history(limit=DELETE_CHECK_HISTORY)]
        except Exception as e:
            logger.warning("Discord existence check failed: {!r}", e)
            return []
        if not fetched:
            return []

        present = set(fetched)
        oldest = 0 if len(fetched) < DELETE_CHECK_HISTORY else min(fetched)
        candidates = [link.dc_id for link in links if link.dc_id >= oldest]
        gone = [dc_id for dc_id in candidates if dc_id not in present]
        if len(candidates) > DELETE_CHECK_GUARD and len(gone) == len(candidates):
            logger.warning("Discord existence check reports everything deleted, ignoring")
            return []
        return gone
