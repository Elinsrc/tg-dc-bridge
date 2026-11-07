# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Elinsrc

import asyncio

from hydrogram import Client, idle
from loguru import logger

from bridge.db import LinkStore
from bridge.dc.client import DiscordBridge
from bridge.dc.gateway import DiscordGateway
from bridge.dc.media import DiscordMedia
from bridge.gif import GifConverter
from bridge.http import HttpClient
from bridge.settings import Settings
from bridge.sync import DeletionSync
from bridge.tg.gateway import TelegramGateway
from bridge.tg.handlers import TelegramHandlers
from bridge.tg.media import TelegramMedia
from bridge.watcher import DeletionWatcher


class BridgeApp:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = LinkStore(settings.db_path, settings.max_links)
        self.http = HttpClient()
        self.gif = GifConverter(settings.max_discord_file)
        self.tg_client: Client | None = None
        self.telegram: TelegramGateway | None = None
        self.dc_client: DiscordBridge | None = None
        self.watcher: DeletionWatcher | None = None

    def build(self) -> None:
        s = self.settings
        self.tg_client = Client(
            name="bridge_bot",
            api_id=s.tg_api_id,
            api_hash=s.tg_api_hash,
            bot_token=s.tg_bot_token,
        )
        self.telegram = TelegramGateway(self.tg_client, s.tg_chat_id)
        self.dc_client = DiscordBridge(s, self.store, self.telegram, DiscordMedia(self.http))
        discord_gateway = DiscordGateway(self.dc_client, self.http, s.discord_webhook_url, s.discord_channel_id)
        sync = DeletionSync(self.store, discord_gateway, self.telegram)
        self.dc_client.bind_sync(sync)
        TelegramHandlers(
            self.tg_client, s, self.store, discord_gateway, sync,
            TelegramMedia(self.tg_client, self.gif, s),
        ).register()
        self.watcher = DeletionWatcher(s, self.store, self.tg_client, self.dc_client, sync)

    async def run(self) -> None:
        dc_task: asyncio.Task | None = None
        idle_task: asyncio.Task | None = None
        watch_task: asyncio.Task | None = None

        await self.store.open()
        await self.http.start()

        try:
            self.build()
            await self.tg_client.start()
            logger.info("Hydrogram client started.")
            if not await self.telegram.can_delete():
                logger.warning("Telegram bot is not an admin with 'Delete messages': deletions from Discord will not work")

            dc_task = asyncio.create_task(self.dc_client.start(self.settings.discord_bot_token), name="discord")
            idle_task = asyncio.create_task(idle(), name="idle")
            if self.settings.delete_check_interval > 0:
                watch_task = asyncio.create_task(self.watcher.run(), name="watcher")

            done, _ = await asyncio.wait({dc_task, idle_task}, return_when=asyncio.FIRST_COMPLETED)
            if dc_task in done and not dc_task.cancelled() and dc_task.exception():
                logger.error("Discord client crashed: {!r}", dc_task.exception())
        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.warning("Forced stop... Bye!")
        finally:
            await self.shutdown([idle_task, dc_task, watch_task])

    async def shutdown(self, tasks: list[asyncio.Task | None]) -> None:
        active = [t for t in tasks if t]
        for task in active:
            if not task.done():
                task.cancel()
        await asyncio.gather(*active, return_exceptions=True)

        if self.dc_client and not self.dc_client.is_closed():
            await self.dc_client.close()
        if self.tg_client and self.tg_client.is_connected:
            await self.tg_client.stop()
        await self.http.stop()
        await self.store.close()
        logger.info("Bridge stopped.")
