# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Elinsrc

from loguru import logger

from bridge.db import LinkStore
from bridge.dc.gateway import DiscordGateway
from bridge.tg.gateway import TelegramGateway


class DeletionSync:
    def __init__(self, store: LinkStore, discord: DiscordGateway, telegram: TelegramGateway):
        self.store = store
        self.discord = discord
        self.telegram = telegram

    async def telegram_deleted(self, tg_ids: list[int]) -> None:
        deleted = set(tg_ids)
        for tg_id in tg_ids:
            link = await self.store.pop_by_tg(tg_id)
            if not link:
                continue
            await self.discord.delete(link)
            leftovers = [tid for tid in link.tg_ids if tid not in deleted]
            if leftovers:
                try:
                    await self.telegram.delete(leftovers)
                except Exception as e:
                    logger.warning("TG leftover delete error: {!r}", e)
            logger.info("TG delete -> DC | tg={} dc={}", tg_id, link.dc_id)

    async def discord_deleted(self, dc_ids: list[int]) -> None:
        links = await self.store.pop_many_by_dc(dc_ids)
        tg_ids = [tid for link in links for tid in link.tg_ids]
        if not tg_ids:
            return
        try:
            await self.telegram.delete(tg_ids)
            logger.info("DC delete -> TG | dc={} tg={}", [link.dc_id for link in links], tg_ids)
        except Exception as e:
            logger.error("Telegram delete error: {!r}", e)
