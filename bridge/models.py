# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Elinsrc

import io
from dataclasses import dataclass, field

import discord


@dataclass
class MsgLink:
    dc_id: int
    tg_ids: list[int] = field(default_factory=list)
    guild_id: int = 0
    origin: str = "tg"
    tg_has_media: bool = False
    reply_header: str = ""
    last_text: str = ""


@dataclass
class OutMedia:
    kind: str
    buf: io.BytesIO
    filename: str
    spoiler: bool = False
    duration: int | None = None


@dataclass
class TgCollected:
    files: list[discord.File] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    drop_text: bool = False


@dataclass
class DcCollected:
    items: list[OutMedia] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    consumed_urls: list[str] = field(default_factory=list)
