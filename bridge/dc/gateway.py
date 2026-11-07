# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Elinsrc

import discord
from loguru import logger

from bridge.http import HttpClient
from bridge.models import MsgLink


class DiscordGateway:
    def __init__(self, client: discord.Client, http: HttpClient, webhook_url: str, channel_id: int):
        self.client = client
        self.http = http
        self.webhook_url = webhook_url
        self.channel_id = channel_id

    @property
    def webhook(self) -> discord.Webhook:
        return discord.Webhook.from_url(self.webhook_url, session=self.http.session)

    async def send_as_user(self, content, username: str, avatar_url: str, files) -> discord.WebhookMessage | None:
        return await self.webhook.send(
            content=content,
            username=username,
            avatar_url=avatar_url,
            files=files,
            allowed_mentions=discord.AllowedMentions.none(),
            wait=True,
        )

    async def edit_as_user(self, dc_id: int, content: str | None) -> None:
        await self.webhook.edit_message(
            dc_id,
            content=content,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def delete(self, link: MsgLink) -> None:
        try:
            if link.origin == "tg":
                await self.webhook.delete_message(link.dc_id)
            else:
                channel = self.client.get_channel(self.channel_id)
                if channel:
                    await channel.get_partial_message(link.dc_id).delete()
        except discord.NotFound:
            pass
        except Exception as e:
            logger.error("Discord delete error: {!r}", e)
