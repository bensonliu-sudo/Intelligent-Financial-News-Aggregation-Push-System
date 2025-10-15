# TODO: 定义数据模型
# TODO: Source模型 - 数据源配置
# TODO: Event模型 - 采集的事件
# TODO: Score模型 - 事件评分
# TODO: Notification模型 - 推送记录

# -*- coding: utf-8 -*-
"""
models.py
定义事件数据模型。注意字段名必须与 tests/test_all.py 里一致，
否则 Step 2 的构造 Event 会失败。
"""

from dataclasses import dataclass
from typing import Optional

@dataclass
class Event:
    # 主键ID（建议用URL+时间的哈希或UUID；此处类型为字符串）
    id: str

    # 发现时间与发布时间（UTC，毫秒）
    ts_detected_utc: int
    ts_published_utc: Optional[int]  # 允许为 None

    # 标题、来源名、原文链接
    headline: str
    source: str
    link: str

    # 市场标签：如 "us" / "crypto"
    market: str

    # 多值字段用分号分隔的字符串保存：如 "NVDA;AMD"
    symbols: str
    categories: str  # 如 "contract;ai upgrade"
    tags: str        # 如 "#AI;#Semis"

    # 打分与推送状态
    score: float
    pushed: int      # 0/1

    # 过期时间（UTC毫秒），超时用于清理
    expires_at_utc: int

    # 线程键：用于节流，如 "NVDA|contract"
    thread_key: str