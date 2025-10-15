# app/main.py
# 串起：collector -> scorer -> notifier -> housekeeper
# 兼容你的现有接口：run_collectors(), run_scorer(), Notifier.push()

from __future__ import annotations
import asyncio
import time
import sys
from pathlib import Path
import yaml
import os

# === 保证包导入稳定 ===
ROOT = Path(__file__).resolve().parents[1]  # intel-hub/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 用**相对导入**对齐包结构
from .collector import run_collectors              # 你已有
from .scorer import run_scorer                     # 你已有
from .notifier import Notifier                     # 你已有（类）
from .storage import init_db, delete_expired       # 你已有


DEFAULT_CFG = {
    "notifier": {
        "schema_version": 1,
        "display_timezone": "Australia/Sydney",
        "retention_hours": 48,
        "dedupe_minutes": 15,
        "critical_threshold": 70,
        "important_threshold": 30,
        "translate_to_zh": False,
        "storage": "sqlite",
        # 统一成“复数”写法，和你的 config.yml 对齐
        "notify_channels": ["telegram"],
        # 新增：启动自检
        "debug_startup_push": False,
    }
}

def load_cfg() -> dict:
    """ops/config.yml 可选；不存在就用默认。"""
    cfg_path = ROOT / "ops" / "config.yml"
    if cfg_path.exists():
        try:
            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            # 深合并（只做最外层浅合并，避免过度魔法）
            out = {**DEFAULT_CFG, **data}
            if "notifier" in data:
                out["notifier"] = {**DEFAULT_CFG["notifier"], **(data.get("notifier") or {})}
            return out
        except Exception as e:
            print(f"[main] 读取 ops/config.yml 失败，使用默认。err={e}")
    return DEFAULT_CFG

async def run_notifier_loop(q_scored: "asyncio.Queue", db, notifier_cfg: dict):
    """
    把队列里的事件交给 Notifier。notifier_cfg 可以是整个 cfg，也可以是 cfg['notifier']。
    """
    # 允许传进来“整份 cfg”或“notifier 子配置”
    if "notifier" in notifier_cfg:
        notifier_cfg = notifier_cfg["notifier"]

    print("[notifier] started")
    notifier = Notifier(notifier_cfg) 
    # ---------- 启动自检推送 ----------
    startup_flag = bool(notifier_cfg.get("debug_startup_push", False))
    print(f"[DEBUG] startup flag: {startup_flag}")

    if startup_flag:
        # 从“配置或环境”取 token/chat_id（不会阻塞真正发送；只是用于日志）
        token = notifier_cfg.get("token") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = notifier_cfg.get("chat_id") or os.environ.get("TELEGRAM_CHAT_ID", "")
        print(f"[DEBUG] env token? {bool(token)}  chat_id? {bool(chat_id)}  channels={notifier_cfg.get('notify_channels')}")

        # 无论是否有 token/chat_id，都让 Notifier 去推；
        # Notifier 内部会自动回退到 stdout，因此不要在这里“跳过”
        from app.models import Event
        now = int(time.time() * 1000)
        ev = Event(
            id=f"boot_sanity_{now}",
            ts_detected_utc=now, ts_published_utc=now,
            headline="(BOOT SANITY) Intel Hub notifier is online ✅",
            source="unit_test", link="https://example.com",
            market="us", symbols="OPEN", categories="contract",
            tags="#sanity", score=95.0, pushed=0,
            expires_at_utc=now + 3600_000, thread_key=f"BOOT|{now}",
        )
          # 交给 Notifier，里面自己决定发 Telegram 还是 stdout
        ok = await notifier.push(ev)
        print(f"[notifier] startup sanity push -> {ok}")
    try:
        while True:
            ev = await q_scored.get()
            try:
                # 你自己的 notifier 会根据分数、去重、静默时段等决定是否真正推送
                ok = await notifier.push(ev)
                if not ok:
                    # 可选：这里打印一下便于观察
                    pass
            except Exception as e:
                print(f"[notifier] push error: {e}")
            finally:
                q_scored.task_done()
    except asyncio.CancelledError:
        print("[notifier] cancelled")
        raise
    finally:
        print("[notifier] finished")
    

async def run_housekeeper(db, every_sec: int = 600):
    """定期清理过期事件，避免库膨胀。"""
    print("[housekeeper] started")
    try:
        while True:
            try:
                now_ms = int(time.time() * 1000)
                await delete_expired(db, now_ms)
            except Exception as e:
                print(f"[housekeeper] delete_expired error: {e}")
            await asyncio.sleep(every_sec)
    except asyncio.CancelledError:
        print("[housekeeper] cancelled")
        raise
    finally:
        print("[housekeeper] finished")

async def main(run_seconds: int = 30):
    cfg = load_cfg()

    db = await init_db(ROOT / "intel.db")

    q_raw: asyncio.Queue = asyncio.Queue()
    q_scored: asyncio.Queue = asyncio.Queue()

    tasks = []
    print("[main] creating tasks…")

    # 1) 采集器 -> q_raw
    tasks.append(asyncio.create_task(run_collectors(q_raw)))
    print("[collector] started")

    # 2) 打分器 -> q_scored（保持你现有 run_scorer 的签名）
    tasks.append(asyncio.create_task(run_scorer(q_raw, q_scored, db)))
    print("[scorer] started")

    # 3) 推送器（Notifier 类）消费 q_scored
    # tasks.append(asyncio.create_task(run_notifier_loop(q_scored, db, cfg.get("notifier", {}))))
#     tasks.append(asyncio.create_task(
#     run_notifier_loop(q_scored, db, {"notifier": cfg.get("notifier", cfg)})
# ))
    tasks.append(asyncio.create_task(run_notifier_loop(q_scored, db, cfg)))
    # 4) 清理器
    tasks.append(asyncio.create_task(run_housekeeper(db, every_sec=600)))

    print(f"[main] running for {run_seconds}s …")
    try:
        if run_seconds and run_seconds > 0:
            # 运行指定秒数
            await asyncio.sleep(run_seconds)
        else:
            # 0 或负数 => 永久运行
            stop = asyncio.Event()
            await stop.wait()   # 永不触发，等同常驻
    except asyncio.CancelledError:
        print("[main] cancelled")
        raise
    finally:
        # 优雅退出
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        print("[main] finished")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-seconds", type=int, default=0)
    args = parser.parse_args()

    # 用 “-m” 方式更稳；但也兼容直接运行
    asyncio.run(main(run_seconds=args.run_seconds))