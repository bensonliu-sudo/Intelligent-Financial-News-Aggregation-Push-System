# TODO: JSON默认解析器模板
# TODO: 通用JSON数据结构解析
# TODO: 字段映射配置
# TODO: 嵌套数据提取
# TODO: 数组处理
# TODO: 数据类型转换

import time
from typing import List, Dict, Union


def parse_json(obj: Union[Dict, List], source_id: str) -> List[Dict]:
    """
    JSON解析器模板 - 示例映射，需要根据具体API修改

    这里展示一个典型的API响应格式示例：
    {
        "items": [
            {
                "title": "新闻标题",
                "url": "https://example.com/news/123",
                "timestamp": 1640995200000,  # UTC毫秒，或者
                "time": "2022-01-01T00:00:00Z"  # ISO格式
            }
        ]
    }

    使用方式:
    1. 修改下面的字段映射逻辑
    2. 调整时间解析方式
    3. 处理嵌套结构

    参数:
        obj: 解析后的JSON对象(dict或list)
        source_id: 数据源ID

    返回:
        事件dict列表
    """
    events = []

    try:
        # 示例1: 如果响应是 {"items": [...]}
        if isinstance(obj, dict) and 'items' in obj:
            items = obj['items']
        # 示例2: 如果响应直接是数组
        elif isinstance(obj, list):
            items = obj
        # 示例3: 如果响应是 {"data": [...]}
        elif isinstance(obj, dict) and 'data' in obj:
            items = obj['data']
        else:
            # TODO: 根据实际API格式调整
            items = []

        for item in items:
            if not isinstance(item, dict):
                continue

            event = {}

            # 提取标题 - 根据API字段名调整
            # 常见字段名: title, headline, subject, name
            event['headline'] = item.get('title') or item.get('headline') or item.get('subject', '')
            if not event['headline']:
                continue

            # 提取链接 - 根据API字段名调整
            # 常见字段名: url, link, href, permalink
            event['link'] = item.get('url') or item.get('link') or item.get('href', '')
            if not event['link']:
                continue

            # 提取时间 - 根据API时间格式调整
            ts_published = None

            # 方式1: 如果是毫秒时间戳
            if 'timestamp' in item:
                ts_published = int(item['timestamp'])

            # 方式2: 如果是秒时间戳
            elif 'time' in item and isinstance(item['time'], (int, float)):
                ts_published = int(item['time'] * 1000)

            # 方式3: 如果是ISO时间字符串
            elif 'time' in item and isinstance(item['time'], str):
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(item['time'].replace('Z', '+00:00'))
                    ts_published = int(dt.timestamp() * 1000)
                except:
                    pass

            # 如果没有时间，使用当前时间
            if not ts_published:
                ts_published = int(time.time() * 1000)

            event['ts_published'] = ts_published
            event['source_id'] = source_id

            # 保存原始数据
            event['raw'] = item

            events.append(event)

    except Exception as e:
        print(f"[json_parser] 解析错误 source_id={source_id}: {e}")

    return events