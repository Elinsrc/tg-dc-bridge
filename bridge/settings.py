# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Elinsrc

from dataclasses import dataclass

import config


@dataclass(frozen=True)
class Settings:
    tg_api_id: int
    tg_api_hash: str
    tg_bot_token: str
    tg_chat_id: int
    discord_bot_token: str
    discord_channel_id: int
    discord_guild_id: int
    discord_webhook_url: str
    emoji_as_images: bool
    emoji_image_limit: int
    max_discord_file_mb: int
    max_links: int
    db_path: str
    log_level: str
    delete_check_interval: int

    @property
    def max_discord_file(self) -> int:
        return self.max_discord_file_mb * 1024 * 1024

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            tg_api_id=config.TG_API_ID,
            tg_api_hash=config.TG_API_HASH,
            tg_bot_token=config.TG_BOT_TOKEN,
            tg_chat_id=config.TG_CHAT_ID,
            discord_bot_token=config.DISCORD_BOT_TOKEN,
            discord_channel_id=config.DISCORD_CHANNEL_ID,
            discord_guild_id=config.DISCORD_GUILD_ID,
            discord_webhook_url=config.DISCORD_WEBHOOK_URL,
            emoji_as_images=config.EMOJI_AS_IMAGES,
            emoji_image_limit=config.EMOJI_IMAGE_LIMIT,
            max_discord_file_mb=config.MAX_DISCORD_FILE_MB,
            max_links=config.MAX_CACHE,
            db_path=config.DB_PATH,
            log_level=config.LOG_LEVEL,
            delete_check_interval=getattr(config, "DELETE_CHECK_INTERVAL", 3),
        )
