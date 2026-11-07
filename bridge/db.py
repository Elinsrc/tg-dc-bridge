# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Elinsrc

import asyncio
from pathlib import Path

import aiosqlite
from loguru import logger

from bridge.models import MsgLink


class LinkStore:
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS links (
        dc_id        INTEGER PRIMARY KEY,
        guild_id     INTEGER NOT NULL DEFAULT 0,
        origin       TEXT    NOT NULL,
        tg_has_media INTEGER NOT NULL DEFAULT 0,
        reply_header TEXT    NOT NULL DEFAULT '',
        last_text    TEXT    NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS link_tg_ids (
        tg_id    INTEGER PRIMARY KEY,
        dc_id    INTEGER NOT NULL REFERENCES links(dc_id) ON DELETE CASCADE,
        position INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_link_tg_ids_dc ON link_tg_ids(dc_id);
    """

    PRUNE_SQL = """
    DELETE FROM links WHERE dc_id <= (
        SELECT dc_id FROM links ORDER BY dc_id DESC LIMIT 1 OFFSET ?
    )
    """

    UPSERT_SQL = """
    INSERT INTO links (dc_id, guild_id, origin, tg_has_media, reply_header, last_text)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(dc_id) DO UPDATE SET
        guild_id     = excluded.guild_id,
        origin       = excluded.origin,
        tg_has_media = excluded.tg_has_media,
        reply_header = excluded.reply_header,
        last_text    = excluded.last_text
    """

    def __init__(self, path: str | Path, max_links: int):
        self.path = Path(path)
        self.max_links = max(int(max_links), 1)
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("LinkStore is not opened")
        return self._db

    async def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.executescript(self.SCHEMA)
        await self._db.execute(self.PRUNE_SQL, (self.max_links,))
        await self._db.commit()
        logger.info("Link store opened: {} (limit={})", self.path, self.max_links)

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def save(self, link: MsgLink) -> None:
        async with self._lock:
            await self.db.execute(
                self.UPSERT_SQL,
                (
                    link.dc_id, link.guild_id, link.origin, int(link.tg_has_media),
                    link.reply_header, link.last_text,
                ),
            )
            await self.db.execute("DELETE FROM link_tg_ids WHERE dc_id = ?", (link.dc_id,))
            await self.db.executemany(
                "INSERT OR REPLACE INTO link_tg_ids (tg_id, dc_id, position) VALUES (?, ?, ?)",
                [(tid, link.dc_id, i) for i, tid in enumerate(link.tg_ids)],
            )
            await self.db.execute(self.PRUNE_SQL, (self.max_links,))
            await self.db.commit()

    async def get_by_dc(self, dc_id: int) -> MsgLink | None:
        async with self.db.execute("SELECT * FROM links WHERE dc_id = ?", (dc_id,)) as cur:
            row = await cur.fetchone()
        return await self._hydrate(row) if row else None

    async def get_by_tg(self, tg_id: int) -> MsgLink | None:
        async with self.db.execute(
            "SELECT l.* FROM links l JOIN link_tg_ids t ON t.dc_id = l.dc_id WHERE t.tg_id = ?",
            (tg_id,),
        ) as cur:
            row = await cur.fetchone()
        return await self._hydrate(row) if row else None

    async def recent(self, limit: int) -> list[MsgLink]:
        async with self.db.execute("SELECT * FROM links ORDER BY dc_id DESC LIMIT ?", (limit,)) as cur:
            rows = await cur.fetchall()
        return [await self._hydrate(row) for row in rows]

    async def update_last_text(self, dc_id: int, text: str) -> None:
        async with self._lock:
            await self.db.execute("UPDATE links SET last_text = ? WHERE dc_id = ?", (text, dc_id))
            await self.db.commit()

    async def pop_many_by_dc(self, dc_ids: list[int]) -> list[MsgLink]:
        popped: list[MsgLink] = []
        async with self._lock:
            for dc_id in dc_ids:
                link = await self.get_by_dc(dc_id)
                if link:
                    popped.append(link)
                    await self.db.execute("DELETE FROM links WHERE dc_id = ?", (dc_id,))
            if popped:
                await self.db.commit()
        return popped

    async def pop_by_dc(self, dc_id: int) -> MsgLink | None:
        popped = await self.pop_many_by_dc([dc_id])
        return popped[0] if popped else None

    async def pop_by_tg(self, tg_id: int) -> MsgLink | None:
        link = await self.get_by_tg(tg_id)
        if not link:
            return None
        return await self.pop_by_dc(link.dc_id)

    async def _hydrate(self, row: aiosqlite.Row) -> MsgLink:
        async with self.db.execute(
            "SELECT tg_id FROM link_tg_ids WHERE dc_id = ? ORDER BY position",
            (row["dc_id"],),
        ) as cur:
            tg_ids = [r["tg_id"] async for r in cur]
        return MsgLink(
            dc_id=row["dc_id"],
            tg_ids=tg_ids,
            guild_id=row["guild_id"],
            origin=row["origin"],
            tg_has_media=bool(row["tg_has_media"]),
            reply_header=row["reply_header"],
            last_text=row["last_text"],
        )
