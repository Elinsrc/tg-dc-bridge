# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Elinsrc

import re

TG_MAX_FILE = 50 * 1024 * 1024
DC_TEXT_LIMIT = 2000
TG_TEXT_LIMIT = 4096
TG_CAPTION_LIMIT = 1024
MAX_DISCORD_FILES = 10
STICKER_CACHE_BYTES = 64 * 1024 * 1024

GIF_TIMEOUT = 60
GIF_MAX_FPS = 50

FORWARD_LABEL = "Forwarded from"
FORWARD_UNKNOWN = "Forwarded message"
UNKNOWN_NAME = "Unknown"

DC_EMOJI_RE = re.compile(r"<(a?):(\w{2,32}):(\d{15,25})>")
DC_URL_RE = re.compile(r"<(https?://[^\s<>]+)>|(https?://[^\s<>]+)")
DC_GIF_LINK_RE = re.compile(
    r"https?://(?:[\w-]+\.)*(?:tenor|giphy|gfycat)\.com/\S+|https?://\S+\.gif(?:\?\S*)?",
    re.I,
)
DC_TIMESTAMP_RE = re.compile(r"<t:(-?\d+)(?::[tTdDfFR])?>")
DC_MASKED_LINK_RE = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")

ATTACHMENT_SPOILER_FLAG = 1 << 3

DELETE_CHECK_LIMIT = 100
DELETE_CHECK_HISTORY = 200
DELETE_CHECK_CHUNK = 100
DELETE_CHECK_GUARD = 3
