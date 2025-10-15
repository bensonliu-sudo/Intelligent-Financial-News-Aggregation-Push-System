# -*- coding: utf-8 -*-
"""
Demo 脚本：启动采集器 + 打分器，持续运行 N 分钟，自动退出。
Usage:
    python tests/run_pipeline_demo.py --minutes 5
"""

import sys
import os
import asyncio
import time
import argparse
from contextlib import suppress

# === 保证能正确 import app ===
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.collector import run_collectors
from app.scorer import run_scorer
from app.storage import init_db


async def main(minutes: int):
    q_raw = asyncio.Queue()
    q_scored = asyncio.Queue()
    db = await init_db("intel.db")

    tasks = await run_collectors(q_raw)
    scorer_task = asyncio.create_task(run_scorer(q_raw, q_scored, db))

    t0 = time.time()
    run_seconds = minutes * 60
    try:
        while time.time() - t0 < run_seconds:
            with suppress(asyncio.TimeoutError):
                ev = await asyncio.wait_for(q_scored.get(), timeout=1.0)
                print(
                    f"[HIGH] {ev.headline} | score={ev.score} | tags={ev.tags} | cats={ev.categories}"
                )
            await asyncio.sleep(0.1)
    finally:
        for t in tasks:
            t.cancel()
        scorer_task.cancel()
        with suppress(Exception):
            await db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run collector+scorer pipeline demo.")
    parser.add_argument("--minutes", type=int, default=1, help="运行时长（分钟）")
    args = parser.parse_args()

    asyncio.run(main(args.minutes))