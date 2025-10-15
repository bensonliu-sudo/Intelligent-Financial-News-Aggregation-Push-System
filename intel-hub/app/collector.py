
from __future__ import annotations

import asyncio
import hashlib
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

import yaml
import httpx
import feedparser

# -------------------- 工具函数 --------------------

def _now_ms() -> int:
    return int(time.time() * 1000)

_CLIENT: Optional[httpx.AsyncClient] = None

def _ensure_client() -> httpx.AsyncClient:
    """全局复用一个 httpx AsyncClient，避免频繁建连。"""
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "intel-hub/1.0"})
    return _CLIENT

def normalize_link(url: Optional[str]) -> Optional[str]:
    """
    规范化链接：去掉 utm_*、ref/ref_src 等统计参数，去掉 fragment。
    让“同文不同链”更容易被识别为同一条。
    """
    if not url:
        return url
    try:
        from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
        u = urlparse(url)
        qs = [
            (k, v)
            for (k, v) in parse_qsl(u.query, keep_blank_values=True)
            if not k.lower().startswith("utm_") and k.lower() not in {"ref", "ref_src"}
        ]
        return urlunparse((u.scheme, u.netloc, u.path, u.params, urlencode(qs, doseq=True), ""))
    except Exception:
        return url

def _published_ts(entry: Any) -> int:
    """
    从 feedparser 的 entry 里取发布时间；没有就用 now。
    """
    try:
        if getattr(entry, "published_parsed", None):
            ts = time.mktime(entry.published_parsed)
            return int(ts * 1000)
        if getattr(entry, "updated_parsed", None):
            ts = time.mktime(entry.updated_parsed)
            return int(ts * 1000)
    except Exception:
        pass
    return _now_ms()

# -------------------- 单源：RSS 轮询 --------------------

async def _poll_rss(src: dict, queue: "asyncio.Queue"):
    """
    轮询 RSS 源，把解析出的条目放入 q_raw。
    你现有的 main 会从 q_raw -> 打分 -> q_scored -> notifier 推送。
    """
    url = src.get("url", "")
    interval = int(src.get("interval_sec", 60))
    source_id = src.get("id", "")

    print(f"[collector] RSS 启动 {source_id} 每 {interval}s")

    client = _ensure_client()
    seen: set[str] = set()  # 运行期去重（避免一轮内重复）

    while True:
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                print(f"[rss] {source_id} 响应失败 status={resp.status_code}")
                await asyncio.sleep(min(interval, 30))
                continue

            feed = feedparser.parse(resp.text)

            # 限制一次处理数量，避免超长列表引发抖动
            for entry in feed.entries[:20]:
                # 标题与链接
                headline = entry.get("title") or entry.get("summary") or ""
                link_raw = entry.get("link") or entry.get("id") or ""
                link = normalize_link(link_raw)

                # 生成稳定的 uid（优先 link，其次 title+published）
                base_uid = link or (headline + str(_published_ts(entry)))
                uid = hashlib.sha1(base_uid.encode("utf-8")).hexdigest()

                if uid in seen:
                    continue
                seen.add(uid)

                ts_pub = _published_ts(entry)
                now = _now_ms()

                # 与你项目的 Event 字段对齐（主流程会在 models/scorer/notifier 再加工）
                ev = {
                    "id": uid,
                    "headline": headline,
                    "link": link,
                    "ts_published": ts_pub,
                    "ts_detected": now,       # 如果你的模型用 ts_detected_utc/ms，请在后续转换
                    "source_id": source_id,
                    "raw": entry,
                }

                await queue.put(ev)
                print(f"[rss] {source_id} 捕获 {headline[:60]}")

            # 正常完成一轮后休眠
            await asyncio.sleep(interval)

        except asyncio.CancelledError:
            print(f"[rss] {source_id} 任务已取消")
            return
        except Exception as e:
            print(f"[rss] {source_id} 异常: {e!r}")
            # 出错做退避，避免频繁报错刷屏
            await asyncio.sleep(min(interval, 60))

# -------------------- 总调度：读取 sources.yml 并启动任务 --------------------

async def run_collectors(queue: "asyncio.Queue") -> List[asyncio.Task]:
    """
    读取 ops/sources.yml，按 type 启动对应采集任务。
    目前实现了 rss，其它类型保持占位（与你现有结构一致）。
    """
    tasks: List[asyncio.Task] = []

    root = Path(__file__).resolve().parents[1]
    sources: List[Dict[str, Any]] = []

    # sources.yml
    try:
        with open(root / "ops" / "sources.yml", "r", encoding="utf-8") as f:
            sources = (yaml.safe_load(f) or {}).get("sources", [])
    except FileNotFoundError:
        print("[collector] 未找到 ops/sources.yml，跳过")
        sources = []

    # universe.yml（如果你需要 watchlist，可在别的采集器里用）
    try:
        with open(root / "ops" / "universe.yml", "r", encoding="utf-8") as f:
            uni = yaml.safe_load(f) or {}
        watchlist = uni.get("clk_map", {}) or uni.get("ck_map", {}) or {}
    except FileNotFoundError:
        watchlist = {}

    for src in sources:
        if not src.get("enabled", True):
            continue
        t = (src.get("type", "") or "").strip().lower()

        if t == "rss":
            tasks.append(asyncio.create_task(_poll_rss(src, queue)))
        elif t == "api":
            # 这里预留位：如果你有 _poll_api，可在此补上
            print(f"[collector] 未实现的类型: api ({src.get('id')})，跳过")
        elif t == "dummy":
            print(f"[collector] 未实现的类型: dummy ({src.get('id')})，跳过")
        elif t == "edgar_submissions":
            print(f"[collector] 未实现的类型: edgar_submissions ({src.get('id')})，跳过")
        else:
            print(f"[collector] 未知类型: {t} ({src})")

    print(f"[collector] 已启动 {len(tasks)} 个采集任务")
    return tasks