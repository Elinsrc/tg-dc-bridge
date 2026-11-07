# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Elinsrc

import html
import re
from datetime import datetime, timezone

from bridge.constants import (
    DC_EMOJI_RE,
    DC_MASKED_LINK_RE,
    DC_TIMESTAMP_RE,
    DC_URL_RE,
    FORWARD_LABEL,
    FORWARD_UNKNOWN,
    TG_TEXT_LIMIT,
)


class DiscordFormatter:
    MULTILINE_QUOTE = "&gt;&gt;&gt; "
    LINE_QUOTE = "&gt; "

    @staticmethod
    def prepare(text: str) -> str:
        return text.replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")

    @staticmethod
    def timestamp(match: re.Match) -> str:
        try:
            moment = datetime.fromtimestamp(int(match.group(1)), timezone.utc)
        except (OverflowError, OSError, ValueError):
            return match.group(0)
        return moment.strftime("%Y-%m-%d %H:%M UTC")

    @classmethod
    def plain(cls, text: str) -> str:
        return DC_TIMESTAMP_RE.sub(cls.timestamp, DC_EMOJI_RE.sub(r":\2:", text))

    @staticmethod
    def forward_quote(name: str | None) -> str:
        label = f"{FORWARD_LABEL} {html.escape(name)}" if name else FORWARD_UNKNOWN
        return f"<blockquote>↪️ {label}</blockquote>\n"

    @staticmethod
    def style_line(line: str) -> str:
        header = re.match(r"^#{1,3} (.+)$", line)
        if header:
            return f"<b>{header.group(1)}</b>"
        subtext = re.match(r"^-# (.+)$", line)
        if subtext:
            return f"<i>{subtext.group(1)}</i>"
        return line

    @classmethod
    def quote_snippet(cls, text: str, limit: int = 70) -> str:
        snippet = text.replace("\n", " ").strip()
        if len(snippet) > limit:
            snippet = snippet[: limit - 3] + "..."
        if snippet.count("||") % 2:
            snippet += "||"
        return cls.to_telegram_html(snippet)

    @classmethod
    def to_telegram_html(cls, text: str) -> str:
        if not text:
            return ""
        stash: list[str] = []

        def keep(s: str) -> str:
            stash.append(s)
            return f"\x00{len(stash) - 1}\x00"

        text = re.sub(
            r"```(?:\w+\n)?(.*?)```",
            lambda m: keep(f"<pre>{html.escape(m.group(1).strip(chr(10)))}</pre>"),
            text, flags=re.S,
        )
        text = re.sub(r"`([^`\n]+)`", lambda m: keep(f"<code>{html.escape(m.group(1))}</code>"), text)
        text = DC_EMOJI_RE.sub(lambda m: keep(html.escape(f":{m.group(2)}:")), text)
        text = DC_TIMESTAMP_RE.sub(lambda m: keep(html.escape(cls.timestamp(m))), text)
        text = DC_MASKED_LINK_RE.sub(
            lambda m: keep(
                f'<a href="{html.escape(m.group(2), quote=True)}">{html.escape(m.group(1))}</a>'
            ),
            text,
        )
        text = DC_URL_RE.sub(lambda m: keep(html.escape(m.group(1) or m.group(2))), text)

        text = html.escape(text, quote=False)
        text = re.sub(r"\|\|(.+?)\|\|", r"<spoiler>\1</spoiler>", text, flags=re.S)
        text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>", text, flags=re.S)
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.S)
        text = re.sub(r"__(.+?)__", r"<u>\1</u>", text, flags=re.S)
        text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text, flags=re.S)
        text = re.sub(r"\*(?!\s)(.+?)(?<!\s)\*", r"<i>\1</i>", text)
        text = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"<i>\1</i>", text)

        out_lines: list[str] = []
        quote_buf: list[str] = []
        multiline = False
        for line in text.split("\n"):
            if multiline:
                quote_buf.append(line)
                continue
            if line.startswith(cls.MULTILINE_QUOTE):
                multiline = True
                quote_buf.append(line[len(cls.MULTILINE_QUOTE):])
                continue
            if line.startswith(cls.LINE_QUOTE):
                quote_buf.append(line[len(cls.LINE_QUOTE):])
                continue
            if quote_buf:
                out_lines.append("<blockquote>" + "\n".join(quote_buf) + "</blockquote>")
                quote_buf = []
            out_lines.append(cls.style_line(line))
        if quote_buf:
            out_lines.append("<blockquote>" + "\n".join(quote_buf) + "</blockquote>")
        text = "\n".join(out_lines)

        return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)

    @classmethod
    def build_texts(
        cls, author: str, raw_text: str, *,
        quote_html: str = "", limit: int = TG_TEXT_LIMIT,
    ) -> tuple[str, str]:
        head = f"<b>{html.escape(author)}</b>"
        text = raw_text

        while True:
            body = cls.to_telegram_html(text)
            full_html = f"{quote_html}{head}{': ' + body if body else ''}"
            if len(full_html) <= limit or not text:
                break
            cut = len(text) - max(len(full_html) - limit, 20) - 1
            text = text[:cut].rstrip() + "…" if cut > 0 else ""

        plain_body = cls.plain(raw_text)
        full_plain = f"{author}{': ' + plain_body if plain_body else ''}"[:limit]
        return full_html, full_plain
