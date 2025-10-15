# -*- coding: utf-8 -*-
"""
app/storage.py
SQLite（aiosqlite）持久化：
- 初始化/建表
- 事件写入（upsert）
- 标记已推送
- 清理过期
- 近期线程去重判断
- 查询最近事件
完全对齐 app.models.Event 字段：
id, ts_detected_utc, ts_published_utc, headline, source, link,
market, symbols, categories, tags, score, pushed, expires_at_utc, thread_key
"""

from __future__ import annotations
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import aiosqlite

# --------- 小工具 ---------
def _now_ms() -> int:
    return int(time.time() * 1000)


# --------- 建表 SQL（严格对齐 Event 字段） ---------
SCHEMA_EVENTS = """
CREATE TABLE IF NOT EXISTS events (
    id               TEXT PRIMARY KEY,
    ts_detected_utc  INTEGER NOT NULL,
    ts_published_utc INTEGER,
    headline         TEXT NOT NULL,
    source           TEXT NOT NULL,
    link             TEXT,
    market           TEXT,
    symbols          TEXT,
    categories       TEXT,
    tags             TEXT,
    score            REAL DEFAULT 0.0,
    pushed           INTEGER DEFAULT 0,
    expires_at_utc   INTEGER,
    thread_key       TEXT
);
"""

SCHEMA_IDX = """
CREATE INDEX IF NOT EXISTS idx_events_detected ON events(ts_detected_utc DESC);
CREATE INDEX IF NOT EXISTS idx_events_thread   ON events(thread_key);
CREATE INDEX IF NOT EXISTS idx_events_score    ON events(score DESC);
CREATE INDEX IF NOT EXISTS idx_events_thread_key ON events(thread_key);
CREATE INDEX IF NOT EXISTS idx_events_link       ON events(link);
"""


# --------- 初始化 ---------
async def init_db(db_path: Union[str, Path]) -> aiosqlite.Connection:
    """
    初始化数据库并返回连接。
    注意：若你之前建过老表结构，建议先删除旧的 intel.db 再初始化，避免列不一致。
    """
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(p))
    # 性能相关 pragma
    await db.execute("PRAGMA journal_mode=WAL;")
    await db.execute("PRAGMA synchronous=NORMAL;")
    await db.execute(SCHEMA_EVENTS)
    for stmt in filter(None, SCHEMA_IDX.split(";")):
        s = stmt.strip()
        if s:
            await db.execute(s + ";")
    await db.commit()
    return db


# --------- 写入 / 更新（幂等） ---------
async def insert_event(db: aiosqlite.Connection, ev: Any) -> bool:
    """
    幂等写入（ON CONFLICT DO UPDATE）。支持 dataclass 或 dict。
    字段（必须）：与 app.models.Event 一致。
    """
    # 兼容 dataclass / dict
    to_dict: Dict[str, Any]
    if hasattr(ev, "__dict__"):
        to_dict = ev.__dict__.copy()
    elif isinstance(ev, dict):
        to_dict = ev.copy()
    else:
        raise TypeError("insert_event: ev must be Event-like or dict")

    def g(k: str, default=None):
        return to_dict.get(k, getattr(ev, k, default))

    id_              = g("id")
    ts_detected_utc  = int(g("ts_detected_utc", 0) or 0)
    ts_published_utc = g("ts_published_utc")
    ts_published_utc = int(ts_published_utc) if ts_published_utc not in (None, "") else None
    headline         = g("headline") or ""
    source           = g("source") or ""
    link             = g("link") or ""
    market           = g("market") or ""
    symbols          = g("symbols") or ""
    categories       = g("categories") or ""
    tags             = g("tags") or ""
    score            = float(g("score", 0.0) or 0.0)
    pushed           = int(g("pushed", 0) or 0)
    expires_at_utc   = int(g("expires_at_utc", 0) or 0)
    thread_key       = g("thread_key") or ""

    if not id_:
        raise ValueError("insert_event: missing id")
    if ts_detected_utc <= 0:
        ts_detected_utc = _now_ms()

    sql = """
    INSERT INTO events(
        id, ts_detected_utc, ts_published_utc, headline, source, link,
        market, symbols, categories, tags, score, pushed, expires_at_utc, thread_key
    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(id) DO UPDATE SET
        ts_detected_utc  = excluded.ts_detected_utc,
        ts_published_utc = excluded.ts_published_utc,
        headline         = excluded.headline,
        source           = excluded.source,
        link             = excluded.link,
        market           = excluded.market,
        symbols          = excluded.symbols,
        categories       = excluded.categories,
        tags             = excluded.tags,
        score            = excluded.score,
        pushed           = MAX(events.pushed, excluded.pushed), -- 已推送不回退
        expires_at_utc   = excluded.expires_at_utc,
        thread_key       = excluded.thread_key
    """
    await db.execute(sql, (
        id_, ts_detected_utc, ts_published_utc, headline, source, link,
        market, symbols, categories, tags, score, pushed, expires_at_utc, thread_key
    ))
    await db.commit()
    return True


# --------- 标记已推送 ---------
async def mark_pushed(db: aiosqlite.Connection, event_id: str) -> None:
    await db.execute("UPDATE events SET pushed=1 WHERE id=?;", (event_id,))
    await db.commit()


# --------- 清理过期 ---------
async def delete_expired(db: aiosqlite.Connection, now_ms: int) -> None:
    """
    删除 expires_at_utc < now_ms 的事件。
    """
    await db.execute("DELETE FROM events WHERE expires_at_utc > 0 AND expires_at_utc < ?;", (now_ms,))
    await db.commit()


# --------- 去重辅助：近期是否已有同线程并已推送 ---------
# 去重辅助：近期是否已有同线程并已推送
async def exists_recent_thread(
    db: aiosqlite.Connection,
    thread_key: str,
    window_minutes: int = 15,   # ← 加默认值，和 config.yml 的 dedupe_minutes 保持一致
) -> bool:
    if not thread_key:
        return False

    cutoff = _now_ms() - window_minutes * 60 * 1000
    sql = """
    SELECT 1 FROM events
    WHERE thread_key = ?
      AND ts_detected_utc >= ?
      AND pushed = 1
    LIMIT 1;
    """
    async with db.execute(sql, (thread_key, cutoff)) as cur:
        row = await cur.fetchone()
    return row is not None

# --------- 查询最近事件（给后端/前端/调试用） ---------
async def get_recent_events(
    db: aiosqlite.Connection,
    *,
    since_ms: Optional[int] = None,
    min_score: float = 0.0,
    limit: int = 200
) -> List[Dict[str, Any]]:
    """
    查询最近的事件，默认回溯48小时。
    """
    if since_ms is None:
        since_ms = _now_ms() - 48 * 3600 * 1000

    sql = """
    SELECT id, ts_detected_utc, ts_published_utc, headline, source, link,
           market, symbols, categories, tags, score, pushed, expires_at_utc, thread_key
      FROM events
     WHERE ts_detected_utc >= ?
       AND score >= ?
     ORDER BY ts_detected_utc DESC
     LIMIT ?;
    """
    out: List[Dict[str, Any]] = []
    async with db.execute(sql, (int(since_ms), float(min_score), int(limit))) as cur:
        async for row in cur:
            out.append({
                "id": row[0],
                "ts_detected_utc": row[1],
                "ts_published_utc": row[2],
                "headline": row[3],
                "source": row[4],
                "link": row[5],
                "market": row[6],
                "symbols": row[7],
                "categories": row[8],
                "tags": row[9],
                "score": row[10],
                "pushed": row[11],
                "expires_at_utc": row[12],
                "thread_key": row[13],
            })
    return out