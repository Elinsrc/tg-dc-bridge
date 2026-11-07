# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Elinsrc

from urllib.parse import quote

from discord.utils import escape_markdown
from hydrogram.types import Message

from bridge.constants import UNKNOWN_NAME


class TelegramFormatter:
    MD_SPECIAL = set("\\*_~|`")
    LINE_START = set("#>")
    RAW_TYPES = {"CODE", "PRE", "URL", "EMAIL", "MENTION", "HASHTAG", "CASHTAG", "BOT_COMMAND", "PHONE_NUMBER"}
    MARKERS = {
        "BOLD": "**",
        "ITALIC": "*",
        "UNDERLINE": "__",
        "STRIKETHROUGH": "~~",
        "SPOILER": "||",
        "CODE": "`",
    }

    @staticmethod
    def user_name(user, default: str = "Player") -> str:
        name = f"{user.first_name or ''} {user.last_name or ''}".strip() or default
        if user.username:
            name += f" (@{user.username})"
        return name

    @staticmethod
    def chat_name(chat, default: str = "Admin") -> str:
        title = chat.title or default
        if chat.username:
            title += f" (@{chat.username})"
        return title

    @staticmethod
    def utf16_index(text: str) -> dict[int, int]:
        mapping: dict[int, int] = {}
        pos = 0
        for i, ch in enumerate(text):
            mapping[pos] = i
            pos += 2 if ord(ch) > 0xFFFF else 1
        mapping[pos] = len(text)
        return mapping

    @classmethod
    def sender_info(cls, message: Message) -> tuple[str, str | None]:
        if message.from_user:
            return cls.user_name(message.from_user)[:80], message.from_user.username
        if message.sender_chat:
            return cls.chat_name(message.sender_chat)[:80], message.sender_chat.username
        return "Player", None

    @classmethod
    def avatar_url(cls, message: Message) -> str:
        display_name, username = cls.sender_info(message)
        if username:
            return f"https://t.me/i/userpic/320/{username}.jpg"
        return (
            f"https://ui-avatars.com/api/?name={quote(display_name)}"
            f"&background=random&size=256&format=png"
        )

    @classmethod
    def forward_name(cls, message: Message) -> str | None:
        origin = getattr(message, "forward_origin", None)
        if origin is not None:
            user = getattr(origin, "sender_user", None)
            if user:
                return cls.user_name(user, UNKNOWN_NAME)
            hidden = getattr(origin, "sender_user_name", None)
            if hidden:
                return hidden
            chat = getattr(origin, "chat", None) or getattr(origin, "sender_chat", None)
            if chat:
                return cls.chat_name(chat, UNKNOWN_NAME)
            return UNKNOWN_NAME

        user = getattr(message, "forward_from", None)
        if user:
            return cls.user_name(user, UNKNOWN_NAME)
        hidden = getattr(message, "forward_sender_name", None)
        if hidden:
            return hidden
        chat = getattr(message, "forward_from_chat", None)
        if chat:
            return cls.chat_name(chat, UNKNOWN_NAME)
        if getattr(message, "forward_date", None):
            return UNKNOWN_NAME
        return None

    @classmethod
    def spoiler_markup(cls, text: str, entities) -> str:
        if not text:
            return ""
        text = str(text)
        index = cls.utf16_index(text)
        opens: set[int] = set()
        closes: set[int] = set()
        for e in entities or []:
            if e.type.name != "SPOILER":
                continue
            start = index.get(e.offset)
            end = index.get(e.offset + e.length)
            if start is None or end is None or start >= end:
                continue
            opens.add(start)
            closes.add(end)
        if not opens:
            return text

        out: list[str] = []
        for i in range(len(text) + 1):
            if i in closes:
                out.append("||")
            if i in opens:
                out.append("||")
            if i == len(text):
                break
            out.append(text[i])
        return "".join(out)

    @classmethod
    def entities_to_discord(cls, text: str, entities) -> str:
        if not text:
            return ""
        text = str(text)
        index = cls.utf16_index(text)

        opens: dict[int, list[tuple[int, int, str]]] = {}
        closes: dict[int, list[tuple[int, int, str]]] = {}
        raw_ranges: list[tuple[int, int]] = []
        quote_ranges: list[tuple[int, int]] = []
        seq = 0

        for e in entities or []:
            start = index.get(e.offset)
            end = index.get(e.offset + e.length)
            if start is None or end is None or start >= end:
                continue
            kind = e.type.name

            if kind in cls.RAW_TYPES:
                raw_ranges.append((start, end))
            if kind in ("BLOCKQUOTE", "EXPANDABLE_BLOCKQUOTE"):
                quote_ranges.append((start, end))
                continue

            if kind == "TEXT_LINK" and getattr(e, "url", None):
                o, c = "[", f"]({e.url})"
            elif kind == "PRE":
                o, c = f"```{getattr(e, 'language', None) or ''}\n", "\n```"
            elif kind in cls.MARKERS:
                o = c = cls.MARKERS[kind]
            else:
                continue

            seq += 1
            opens.setdefault(start, []).append((end - start, seq, o))
            closes.setdefault(end, []).append((start, seq, c))

        quote_starts = {s for s, _ in quote_ranges}
        out: list[str] = []

        for i in range(len(text) + 1):
            for _, _, c in sorted(closes.get(i, []), key=lambda x: (-x[0], -x[1])):
                out.append(c)
            if i in quote_starts:
                if out and not out[-1].endswith("\n"):
                    out.append("\n")
                out.append("> ")
            for _, _, o in sorted(opens.get(i, []), key=lambda x: (-x[0], x[1])):
                out.append(o)
            if i == len(text):
                break

            ch = text[i]
            in_raw = any(s <= i < e for s, e in raw_ranges)
            at_line_start = i == 0 or text[i - 1] == "\n"
            if ch == "\n" and any(s <= i < e for s, e in quote_ranges):
                out.append("\n> ")
            elif ch in cls.MD_SPECIAL and not in_raw:
                out.append("\\" + ch)
            elif ch in cls.LINE_START and at_line_start and not in_raw:
                out.append("\\" + ch)
            else:
                out.append(ch)

        return "".join(out)

    @classmethod
    def text_for_discord(cls, message: Message) -> str:
        if message.text:
            return cls.entities_to_discord(message.text, message.entities)
        if message.caption:
            return cls.entities_to_discord(message.caption, message.caption_entities)
        return ""

    @staticmethod
    def special_text(message: Message) -> str:
        poll = getattr(message, "poll", None)
        if poll:
            options = "\n".join(f"• {escape_markdown(str(o.text))}" for o in poll.options)
            return f"📊 **{escape_markdown(str(poll.question))}**\n{options}"

        venue = getattr(message, "venue", None)
        if venue and venue.location:
            loc = venue.location
            title = escape_markdown(f"{venue.title}, {venue.address}")
            return f"📍 {title}\nhttps://www.google.com/maps?q={loc.latitude},{loc.longitude}"

        location = getattr(message, "location", None)
        if location:
            return f"📍 https://www.google.com/maps?q={location.latitude},{location.longitude}"

        contact = getattr(message, "contact", None)
        if contact:
            name = f"{contact.first_name or ''} {contact.last_name or ''}".strip()
            return f"👤 {escape_markdown(name)}: {contact.phone_number}"

        dice = getattr(message, "dice", None)
        if dice:
            return f"{dice.emoji} {dice.value}"
        return ""

    @staticmethod
    def custom_emoji_entities(message: Message) -> list:
        entities = message.entities or message.caption_entities or []
        return [e for e in entities if e.type.name == "CUSTOM_EMOJI"]

    @classmethod
    def custom_emoji_ids(cls, message: Message) -> list[int]:
        ids = [int(e.custom_emoji_id) for e in cls.custom_emoji_entities(message)]
        return list(dict.fromkeys(ids))

    @classmethod
    def is_only_custom_emoji(cls, message: Message) -> bool:
        text = str(message.text or message.caption or "")
        covered = sum(e.length for e in cls.custom_emoji_entities(message))
        total = sum(2 if ord(c) > 0xFFFF else 1 for c in text if not c.isspace())
        return covered > 0 and covered == total
