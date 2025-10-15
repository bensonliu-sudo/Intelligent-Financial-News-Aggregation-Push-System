# -*- coding: utf-8 -*-
"""
tests/test_storage.py
验证 app/storage.py 与 Event 模型对接是否正常：
1) init_db -> insert_event
2) get_recent_events 能查回刚插入的数据
"""
# === 保证能正确 import app ===
import sys,os
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.collector import run_collectors
from app.scorer import run_scorer
from app.storage import init_db
import asyncio
import time
from pathlib import Path

from app.storage import init_db, insert_event, get_recent_events
# 尝试导入你的 Event；若构造失败，本测试会退回 dict 方式
try:
    from app.models import Event  # 你项目里的 Event
except Exception:  # noqa
    Event = None


def now_ms() -> int:
    return int(time.time() * 1000)


async def main():
    root = Path(__file__).resolve().parents[1]
    db_path = root / "intel.db"
    db = await init_db(db_path)

    # 唯一ID，避免冲突
    uid = f"test_storage_{int(time.time())}"

    # 事件公共字段
    ts = now_ms()
    payload = dict(
        id=uid,
        ts_detected_utc=ts,
        ts_published_utc=ts,
        headline="(TEST) Broadcom and Canonical expand partnership to optimize VMware Cloud Foundation",
        source="broadcom_news",
        link="https://example.com/test",
        market="us",
        symbols="AVGO",
        categories="partnership;cloud",
        tags="#AI;#Semis",
        score=80.0,
        pushed=0,
        expires_at_utc=ts + 24 * 3600 * 1000,
        thread_key="AVGO|partnership",
        raw={"test": True},
    )

    # 优先尝试用 Event 构造；失败则用 dict
    ev_obj = None
    if Event is not None:
        try:
            ev_obj = Event(**payload)  # 如果你的 Event 接口不同，会抛异常
        except Exception:
            ev_obj = None

    to_write = ev_obj if ev_obj is not None else payload

    # 写入（幂等 upsert）
    ok = await insert_event(db, to_write)
    if not ok:
        raise SystemExit("❌ insert_event 返回 False")

    # 查询
    rows = await get_recent_events(db, since_ms=ts - 60_000, min_score=0, limit=200)
    ids = [r["id"] for r in rows]
    if uid not in ids:
        # 打印一条调试信息帮助定位
        print("rows sample (top 3):", rows[:3])
        raise SystemExit("❌ 查询结果里没有刚插入的事件")

    print("OK ✅")


if __name__ == "__main__":
    asyncio.run(main())