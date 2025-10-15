
"""
app/notifier.py
推送模块：消费 scorer 输出的高优事件并发送到 Telegram（或回退到 stdout）
- 读取 ops/config.yml（30s 热加载）
- 支持 quiet hours（免打扰）
- 去重/节流：按 thread_key 在窗口内只推分数更高的；可选批量合并
- 简单英文→中文占位翻译（后续可替换为真实翻译 API）
"""

from __future__ import annotations
import os
import time
import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Optional, Dict, Tuple

import httpx
import yaml

from app.models import Event
# from app.main import load_cfg


# ------------------------------------------------------------
# 工具函数
# ------------------------------------------------------------

def _now_ms() -> int:
    return int(time.time() * 1000)


def _load_cfg() -> dict:
    """读取 ops/config.yml；不存在则返回默认"""
    root = Path(__file__).resolve().parents[1]
    p = root / "ops" / "config.yml"
    if not p.exists():
        # 最小默认配置
        return {
            "notifier": {
                "channel": "telegram",
                "translate_to_zh": True,
                "quiet_hours": "00:00-00:00",
                "batch_window_sec": 0,
                "dedupe_minutes": 30,
                "retry": {"max_times": 3, "backoff_sec": 2},
            },
            "important_threshold": 70,
            "critical_threshold": 90,
            "display_timezone": "America/New_York",
        }
    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    # 填充默认
    data.setdefault("notifier", {})
    n = data["notifier"]
    n.setdefault("channel", "telegram")
    n.setdefault("translate_to_zh", True)
    n.setdefault("quiet_hours", "00:00-00:00")
    n.setdefault("batch_window_sec", 0)
    n.setdefault("dedupe_minutes", 30)
    n.setdefault("retry", {"max_times": 3, "backoff_sec": 2})
    data.setdefault("important_threshold", 70)
    data.setdefault("critical_threshold", 90)
    data.setdefault("display_timezone", "America/New_York")
    return data


def _parse_hhmm(s: str) -> int:
    """'HH:MM' -> 分钟数"""
    hh, mm = s.split(":")
    return int(hh) * 60 + int(mm)


def _in_quiet_hours(rng: str) -> bool:
    """
    quiet_hours: 'HH:MM-HH:MM' 本地时间
    若起终相等表示关闭免打扰（0 长度）
    若跨日（如 23:00-07:30）也能正确处理
    """
    if not rng or "-" not in rng:
        return False
    try:
        start, end = rng.split("-")
        start_m = _parse_hhmm(start)
        end_m = _parse_hhmm(end)
        now_local = time.localtime()
        now_m = now_local.tm_hour * 60 + now_local.tm_min
        if start_m == end_m:
            return False  # 关闭
        if start_m < end_m:
            return start_m <= now_m < end_m
        # 跨午夜
        return now_m >= start_m or now_m < end_m
    except Exception:
        return False


def _truncate(s: str, limit: int = 3500) -> str:
    if s is None:
        return ""
    return s if len(s) <= limit else s[:limit - 3] + "..."


# 非常简单的术语替换表（占位）
_EN2ZH = {
    "invest": "投资",
    "investment": "投资",
    "contract": "合同",
    "order": "订单",
    "partnership": "战略合作",
    "acquire": "收购",
    "acquisition": "收购",
    "buyback": "回购",
    "guidance": "指引",
    "appoint": "任命",
    "resign": "辞任",
    "management change": "管理层变更",
    "milestone": "里程碑",
    "breakthrough": "技术突破",
    "upgrade": "升级",
    "rwa": "RWA",
    "spot etf": "现货ETF",
    "ipo": "IPO",
}


def _translate_to_zh(text: str) -> str:
    """极简占位翻译：做一些术语替换，其余原样返回"""
    if not text:
        return text
    low = text.lower()
    for k, v in _EN2ZH.items():
        if k in low:
            low = low.replace(k, v)
    # 简单处理 Ray-Ban 歧义
    low = low.replace("ray-ban", "RayBan")
    return low


# ------------------------------------------------------------
# 渠道适配器
# ------------------------------------------------------------

# ===== notifier.py 关键改动 =====
import os, random
import httpx

class _TelegramAdapter:
    def __init__(self, token: str, chat_id: str, retry: dict[int, int]):
        self._token = token
        self._chat_id = chat_id
        self._retry = retry
        self._client: Optional[httpx.AsyncClient] = None

    def _client_get(self) -> httpx.AsyncClient:
        # 复用，读系统代理；缩短超时，HTTP/2 更稳；保持连接池
        if self._client is None:
            timeout = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=30.0)
            proxies = None
            # 允许从环境变量或配置透传代理（可选）
            # 例如在 main 里把 notifier_cfg['proxies'] 放到环境变量里
            if os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY"):
                proxies = {"all://": os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")}
            self._client = httpx.AsyncClient(
                timeout=timeout,
                http2=True,
                trust_env=True,   # <== 读取系统代理/CERT
                proxies=proxies
            )
        return self._client

    async def send(self, text: str) -> bool:
        """
        发送 Telegram；尊重 429/5xx；最终失败才简短打印。
        """
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }

        max_times = int(self._retry.get("max_times", 3))
        backoff  = int(self._retry.get("backoff_sec", 2))

        last_err = None

        for attempt in range(1, max_times + 1):
            try:
                r = await self._client_get().post(url, data=payload)
                # Telegram 常见：非 200 也会给 JSON
                data = None
                try:
                    data = r.json()
                except Exception:
                    data = None

                if r.status_code == 200 and (data is None or data.get("ok", True) is True):
                    return True

                # 429/5xx：可重试
                if r.status_code == 429 or 500 <= r.status_code < 600:
                    retry_after = 0
                    try:
                        j = data or r.json()
                        retry_after = int(j.get("parameters", {}).get("retry_after", 0))
                    except Exception:
                        pass
                    # 指数退避 + 抖动，优先使用服务端给的 retry_after
                    sleep_sec = retry_after or (backoff * (2 ** (attempt - 1)))
                    sleep_sec = min(sleep_sec, 30)  # 上限 30s，避免拉太长
                    sleep_sec += random.uniform(0, 0.6)
                    await asyncio.sleep(sleep_sec)
                    continue

                # 其他 4xx：直接失败，记录头 300 字符即可
                last_err = f"http {r.status_code}: {(r.text or '')[:300]}"
                break

            except Exception as e:
                last_err = repr(e)
                # 网络抖动：也按退避重试
                sleep_sec = backoff * (2 ** (attempt - 1)) + random.uniform(0, 0.6)
                await asyncio.sleep(min(sleep_sec, 20))
                continue

        # 只在最终失败时打一条
        print(f"[notifier] telegram send failed after {max_times} attempts: {last_err}")
        return False

    async def close(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class _StdoutAdapter:
    async def send(self, text: str) -> bool:
        print("\n" + text + "\n")
        return True

    async def close(self):
        return


# ------------------------------------------------------------
# Notifier 主体
# ------------------------------------------------------------

class Notifier:
    def __init__(self, cfg: Optional[dict] = None):
        raw = cfg or load_cfg()

        # ---- 规范化，确保 self._cfg 就是一份“notifier 子配置” ----
        if "notifier" in raw:
            self._cfg = raw["notifier"]
        else:
            self._cfg = raw

        self._cfg_reload_ms = _now_ms()
        self._cfg_last_mtime = None

        # 发送缓存
        self._sent_cache: Dict[str, Tuple[float, int]] = {}
        self._batch_state: Dict[str, dict] = {}

        # 从环境变量读取 token/chat_id（配置里也允许覆盖）
        token = self._cfg.get("token") or os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = self._cfg.get("chat_id") or os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        retry = self._cfg.get("retry", 1)

        # ---- 这里修复：支持 notify_channels ----
        channels = self._cfg.get("notify_channels") or []
        if "telegram" in channels and token and chat_id:
            self._adapter = _TelegramAdapter(token, chat_id, retry)
            self._channel = "telegram"
        else:
            self._adapter = _StdoutAdapter()
            self._channel = "stdout"
            if "telegram" in channels:
                print("[notifier] TELEGRAM_BOT_TOKEN/CHAT_ID 缺失，自动降级为 stdout")

        # 批量窗口参数
        self._batch_window_sec = int(self._cfg.get("batch_window_sec", 0))

    async def start(self, q_in: "asyncio.Queue") -> None:
        """常驻：消费队列并按策略推送"""
        try:
            while True:
                # 配置热加载（30s 一次）
                if _now_ms() - self._cfg_reload_ms > 30 * 1000:
                    self._try_reload_cfg()

                ev: Event = await q_in.get()

                # 免打扰：直接打印为“muted”记录（不推送）
                if _in_quiet_hours(self._cfg.get("quiet_hours", "")):
                    text = self._format_text(ev, muted=True)
                    await self._adapter.send(text)
                    continue

                # 去重/节流
                if self._is_duplicated(ev):
                    continue

                # 批量窗口
                if self._batch_window_sec > 0 and ev.thread_key:
                    key = ev.thread_key
                    now = _now_ms()
                    st = self._batch_state.get(key)
                    if st is None:
                        self._batch_state[key] = {"t0": now, "best": ev, "n": 1}
                        continue
                    # 更新最佳
                    if ev.score > st["best"].score:
                        st["best"] = ev
                    st["n"] += 1
                    # 到期推送
                    if now - st["t0"] >= self._batch_window_sec * 1000:
                        text = self._format_text(st["best"], batch_n=st["n"])
                        await self._adapter.send(text)
                        self._mark_sent(st["best"])
                        self._batch_state.pop(key, None)
                    continue

                # 直接推送
                ok = await self.push(ev)
                if ok:
                    self._mark_sent(ev)

        except asyncio.CancelledError:
            # 退出前 flush 一下批量窗口
            if self._batch_window_sec > 0:
                for key, st in list(self._batch_state.items()):
                    text = self._format_text(st["best"], batch_n=st["n"])
                    await self._adapter.send(text)
                    self._mark_sent(st["best"])
                self._batch_state.clear()
            return

    async def push(self, ev: Event) -> bool:
        """单条推送（直接通过适配器发送）"""
        text = self._format_text(ev)
        return await self._adapter.send(text)

    # --------------- 内部方法 ---------------

    def _is_duplicated(self, ev: Event) -> bool:
        """同 thread_key 在窗口内只推更高分；窗口默认 dedupe_minutes"""
        key = ev.thread_key or ""
        if not key:
            return False
        win_min = int(self._cfg.get("dedupe_minutes", 30))
        now = _now_ms()
        last = self._sent_cache.get(key)
        if last is None:
            return False
        last_score, last_ts = last
        if now - last_ts > win_min * 60 * 1000:
            return False
        # 分数不超过上次 => 忽略
        if ev.score <= last_score:
            return True
        return False

    def _mark_sent(self, ev: Event) -> None:
        key = ev.thread_key or ""
        if not key:
            return
        self._sent_cache[key] = (float(ev.score or 0.0), _now_ms())

    def _format_text(self, ev: Event, muted: bool = False, batch_n: int = 0) -> str:
        """统一的消息格式"""
        score = float(ev.score or 0.0)
        important = int(self._cfg.get("important_threshold", 70))
        critical = int(self._cfg.get("critical_threshold", 90))
        level = "🟢重要" if score >= important else "✅提示"
        if score >= critical:
            level = "🔴特别重要"

        # 标签
        tags = (ev.tags or "").strip()
        if tags and not tags.startswith("#"):
            # 兼容分号/逗号
            tags = "#" + tags.replace(";", " #").replace(",", " #")

        # 标题 + 可选中文
        headline = ev.headline or ""
        text = f"{level} {tags}\n{headline}"

        if self._cfg.get("translate_to_zh", True):
            zh = _translate_to_zh(headline)
            if zh and zh != headline:
                text += f"\n【中译】{zh}"

        cats = ev.categories or "-"
        syms = ev.symbols or "-"
        link = ev.link or "-"
        src = getattr(ev, "source", None) or getattr(ev, "source_id", None) or "-"

        ts_pub = ev.ts_published_utc or 0
        ts_det = ev.ts_detected_utc or 0

        if batch_n > 1:
            text += f"\n(合并 {batch_n} 条更新)"

        text += (
            f"\nSource: {src} | Score: {score:.1f}"
            f"\nCats: {cats}"
            f"\nTicker: {syms}"
            f"\nLink: {link}"
            f"\nPublished(UTC): {ts_pub} | Detected: {ts_det}"
        )

        if muted:
            text += "\n(quiet hours – muted)"

        return _truncate(text, 3500)

    def _try_reload_cfg(self) -> None:
        """30s 热加载配置（若文件 mtime 变化则重载）"""
        root = Path(__file__).resolve().parents[1]
        p = root / "ops" / "config.yml"
        self._cfg_reload_ms = _now_ms()
        try:
            m = p.stat().st_mtime if p.exists() else None
            if self._cfg_last_mtime is None or m != self._cfg_last_mtime:
                self._cfg = _load_cfg()
                self._cfg_last_mtime = m
                # 刷新批量窗口配置
                self._batch_window_sec = int(self._cfg.get("batch_window_sec", 0))
                # 刷新模式：若一开始缺 token/chat 则保持 stdout；避免运行时突然切换造成困惑
                print("[notifier] 配置已热加载")
        except Exception as e:
            print(f"[notifier] 配置热加载失败: {e}")

    async def close(self):
        if isinstance(self._adapter, _TelegramAdapter):
            await self._adapter.close()