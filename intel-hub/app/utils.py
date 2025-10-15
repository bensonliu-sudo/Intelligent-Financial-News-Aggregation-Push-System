# TODO: 工具模块
# TODO: 时区转换工具
# TODO: 配置热加载机制
# TODO: 翻译API占位接口
# TODO: 英文词形匹配（单复数、时态）
# TODO: 日志工具
# TODO: 通用辅助函数

import re
import time
from typing import Tuple


def compile_english_stem(stem: str) -> re.Pattern:
    """
    为英文词根编译正则，支持词形变化匹配

    参数:
        stem: 英文词根（小写）

    返回:
        编译后的正则表达式，匹配词根及其变形
    """
    # 构造正则模式：\b词根(s|es|ed|ing)?\b
    pattern = rf'\b{re.escape(stem)}(s|es|ed|ing)?\b'
    return re.compile(pattern, re.IGNORECASE)


def now_ms() -> int:
    """
    获取当前时间的UTC毫秒时间戳

    返回:
        当前时间的毫秒时间戳
    """
    return int(time.time() * 1000)


def norm_text_for_match(s: str) -> Tuple[str, str]:
    lower = s.lower()
    # 避免 ray-ban 命中 ban
    lower = lower.replace("ray-ban", "rayban")
    return lower, s