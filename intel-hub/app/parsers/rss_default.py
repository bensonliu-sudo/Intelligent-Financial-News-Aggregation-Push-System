# TODO: RSS默认解析器
# TODO: RSS/Atom feed解析
# TODO: 标题、内容、时间提取
# TODO: 作者信息提取
# TODO: 标签和分类处理
# TODO: 编码自动检测

import time
import feedparser
import datetime
from typing import List, Dict, Optional


def parse_rss(text: str, source_id: str) -> List[Dict]:
    """
    解析RSS/Atom内容，返回原始事件dict列表

    参数:
        text: RSS/Atom XML文本
        source_id: 数据源ID

    返回:
        事件dict列表，每个包含:
        - headline: 标题
        - link: 链接
        - ts_published: 发布时间(UTC毫秒)
        - source_id: 数据源ID
        - raw: 原始数据(可选)
    """
    events = []

    try:
        # 使用feedparser解析
        feed = feedparser.parse(text)

        # 遍历所有条目
        for entry in feed.get('entries', []):
            event = {}

            # 提取标题
            event['headline'] = entry.get('title', '').strip()
            if not event['headline']:
                continue

            # 提取链接
            event['link'] = entry.get('link', '').strip()
            if not event['link']:
                continue

            # 提取发布时间
            ts_published = None

            # 尝试从published_parsed获取时间
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                try:
                    dt = datetime.datetime(*entry.published_parsed[:6], tzinfo=datetime.timezone.utc)
                    ts_published = int(dt.timestamp() * 1000)
                except:
                    pass

            # 如果没有published_parsed，尝试updated_parsed
            if not ts_published and hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                try:
                    dt = datetime.datetime(*entry.updated_parsed[:6], tzinfo=datetime.timezone.utc)
                    ts_published = int(dt.timestamp() * 1000)
                except:
                    pass

            # 如果还是没有时间，使用当前时间
            if not ts_published:
                ts_published = int(time.time() * 1000)

            event['ts_published'] = ts_published
            event['source_id'] = source_id

            # 保存原始数据供调试
            event['raw'] = {
                'title': entry.get('title'),
                'link': entry.get('link'),
                'published': entry.get('published'),
                'updated': entry.get('updated'),
                'summary': entry.get('summary', '')[:200]  # 只保留前200字符
            }

            events.append(event)

    except Exception as e:
        print(f"[rss_parser] 解析错误 source_id={source_id}: {e}")

    return events