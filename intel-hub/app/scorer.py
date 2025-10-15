# TODO: 关键词分类与打分模块
# TODO: 关键词匹配引擎
# TODO: 多级打分逻辑
# TODO: 主题分类
# TODO: 评分权重计算
# TODO: 历史数据分析

import asyncio
import hashlib
import time
import yaml
import re
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional
import aiosqlite

from app.models import Event
from app.storage import insert_event, exists_recent_thread
from app.utils import compile_english_stem, now_ms, norm_text_for_match


class ScorerConfig:
    """评分器配置类，支持热加载"""

    def __init__(self):
        self.last_reload = 0
        self.reload_interval = 30  # 30秒热加载一次

        # 配置数据
        self.config = {}
        self.keywords = {}
        self.topics = {}
        self.universe = {}

        # 编译后的正则表达式缓存
        self.english_patterns = {}

        self._load_all_configs()

    def _load_all_configs(self):
        """加载所有配置文件"""
        try:
            root_path = Path(__file__).parent.parent / "ops"

            # 加载config.yml
            with open(root_path / "config.yml", 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f) or {}

            # 加载keywords.yml
            with open(root_path / "keywords.yml", 'r', encoding='utf-8') as f:
                self.keywords = yaml.safe_load(f) or {}

            # 加载topics.yml
            with open(root_path / "topics.yml", 'r', encoding='utf-8') as f:
                self.topics = yaml.safe_load(f) or {}

            # 加载universe.yml
            with open(root_path / "universe.yml", 'r', encoding='utf-8') as f:
                self.universe = yaml.safe_load(f) or {}

            # 编译英文关键词正则
            self._compile_english_patterns()

            self.last_reload = time.time()
            print("[scorer] 配置加载完成")

        except Exception as e:
            print(f"[scorer] 配置加载失败: {e}")

    def _compile_english_patterns(self):
        """编译英文关键词的正则表达式"""
        self.english_patterns.clear()

        # 编译tier1关键词
        tier1 = self.keywords.get('tiers', {}).get('tier1', [])
        for keyword in tier1:
            if keyword.isascii() and keyword.islower():
                self.english_patterns[keyword] = compile_english_stem(keyword)

        # 编译tier2关键词
        tier2 = self.keywords.get('tiers', {}).get('tier2', [])
        for keyword in tier2:
            if keyword.isascii() and keyword.islower():
                self.english_patterns[keyword] = compile_english_stem(keyword)

        # 编译负面关键词
        negatives = self.keywords.get('negatives', [])
        for keyword in negatives:
            if keyword.isascii() and keyword.islower():
                self.english_patterns[keyword] = compile_english_stem(keyword)

    def should_reload(self) -> bool:
        """检查是否需要重新加载配置"""
        return time.time() - self.last_reload > self.reload_interval

    def reload_if_needed(self):
        """如果需要则重新加载配置"""
        if self.should_reload():
            self._load_all_configs()


# 全局配置实例
_scorer_config = ScorerConfig()


def _check_blacklist(headline: str, source_id: str) -> bool:
    """
    检查黑名单

    返回:
        True: 应该丢弃
        False: 可以继续处理
    """
    # 检查来源黑名单
    source_blacklist = _scorer_config.keywords.get('source_blacklist', [])
    if source_id in source_blacklist:
        print(f"[scorer] 丢弃黑名单来源: {source_id}")
        return True

    # 检查关键词黑名单
    keyword_blacklist = _scorer_config.keywords.get('keyword_blacklist', [])
    lower_text, _ = norm_text_for_match(headline)

    for blackword in keyword_blacklist:
        if isinstance(blackword, str):
            if blackword.isascii():
                # 英文黑名单词
                if blackword.lower() in lower_text:
                    print(f"[scorer] 丢弃含黑名单词: {blackword}")
                    return True
            else:
                # 中文黑名单词
                if blackword in headline:
                    print(f"[scorer] 丢弃含黑名单词: {blackword}")
                    return True

    return False


def _extract_symbols(headline: str) -> str:
    """
    从标题中提取股票代码

    返回:
        分号分隔的股票代码字符串
    """
    watchlist = _scorer_config.universe.get('watchlist', [])
    found_symbols = []

    for symbol in watchlist:
        if isinstance(symbol, str) and symbol.upper() in headline.upper():
            found_symbols.append(symbol.upper())

    return ';'.join(found_symbols)


def _match_keywords(headline: str) -> Tuple[List[str], List[str], int, int, int]:
    """
    匹配关键词并计算命中次数

    返回:
        (tier1_keywords, tier2_keywords, tier1_hits, tier2_hits, negative_hits)
    """
    lower_text, original_text = norm_text_for_match(headline)

    tier1_keywords = []
    tier2_keywords = []
    tier1_hits = 0
    tier2_hits = 0
    negative_hits = 0

    # 匹配tier1关键词
    tier1_list = _scorer_config.keywords.get('tiers', {}).get('tier1', [])
    for keyword in tier1_list:
        if isinstance(keyword, str):
            if keyword.isascii() and keyword.islower():
                # 英文关键词，使用正则匹配
                pattern = _scorer_config.english_patterns.get(keyword)
                if pattern and pattern.search(lower_text):
                    tier1_keywords.append(keyword)
                    tier1_hits += 1
            else:
                # 中文关键词，直接子串匹配
                if keyword in original_text:
                    tier1_keywords.append(keyword)
                    tier1_hits += 1

    # 匹配tier2关键词
    tier2_list = _scorer_config.keywords.get('tiers', {}).get('tier2', [])
    for keyword in tier2_list:
        if isinstance(keyword, str):
            if keyword.isascii() and keyword.islower():
                # 英文关键词，使用正则匹配
                pattern = _scorer_config.english_patterns.get(keyword)
                if pattern and pattern.search(lower_text):
                    tier2_keywords.append(keyword)
                    tier2_hits += 1
            else:
                # 中文关键词，直接子串匹配
                if keyword in original_text:
                    tier2_keywords.append(keyword)
                    tier2_hits += 1

    # 匹配负面关键词
    negatives = _scorer_config.keywords.get('negatives', [])
    for keyword in negatives:
        if isinstance(keyword, str):
            if keyword.isascii() and keyword.islower():
                # 英文关键词，使用正则匹配
                pattern = _scorer_config.english_patterns.get(keyword)
                if pattern and pattern.search(lower_text):
                    negative_hits += 1
            else:
                # 中文关键词，直接子串匹配
                if keyword in original_text:
                    negative_hits += 1

    return tier1_keywords, tier2_keywords, tier1_hits, tier2_hits, negative_hits


def _match_topics(headline: str) -> List[str]:
    """
    匹配话题标签

    返回:
        匹配到的hashtag列表
    """
    matched_hashtags = []
    topics = _scorer_config.topics.get('topics', {})

    for topic_name, topic_config in topics.items():
        tags = topic_config.get('tags', [])
        hashtag = topic_config.get('hashtag', '')

        for tag in tags:
            if isinstance(tag, str):
                if tag in headline:
                    if hashtag and hashtag not in matched_hashtags:
                        matched_hashtags.append(hashtag)
                    break

    return matched_hashtags


def _calculate_score(tier1_hits: int, tier2_hits: int, negative_hits: int,
                    has_watchlist_symbol: bool) -> float:
    """
    计算事件评分

    返回:
        计算得出的分数
    """
    weights = _scorer_config.keywords.get('weights', {})

    score = weights.get('source_rss_base', 20)
    score += tier1_hits * weights.get('tier1', 50)
    score += tier2_hits * weights.get('tier2', 25)
    score += negative_hits * weights.get('negative', -30)

    if has_watchlist_symbol:
        score += weights.get('watchlist_bonus', 10)

    return float(score)


def _create_event_from_raw(raw_event: Dict[str, Any]) -> Event:
    """
    将原始事件dict转换为Event对象

    参数:
        raw_event: 原始事件数据

    返回:
        Event对象
    """
    headline = raw_event.get('headline', '')
    link = raw_event.get('link', '')
    source_id = raw_event.get('source_id', '')
    ts_published = raw_event.get('ts_published', now_ms())

    # 生成事件ID
    event_id = hashlib.sha1(f"{source_id}|{link}".encode()).hexdigest()

    # 提取股票代码
    symbols = _extract_symbols(headline)

    # 匹配关键词
    tier1_keywords, tier2_keywords, tier1_hits, tier2_hits, negative_hits = _match_keywords(headline)

    # 匹配话题
    hashtags = _match_topics(headline)

    # 计算分数
    has_watchlist_symbol = bool(symbols)
    score = _calculate_score(tier1_hits, tier2_hits, negative_hits, has_watchlist_symbol)

    # 构造categories
    all_keywords = tier1_keywords + tier2_keywords
    categories = ';'.join(all_keywords) if all_keywords else 'general'

    # 构造tags
    tags = ';'.join(hashtags) if hashtags else ''

    # 构造thread_key
    primary_symbol = symbols.split(';')[0] if symbols else source_id
    primary_category = tier1_keywords[0] if tier1_keywords else (tier2_keywords[0] if tier2_keywords else 'general')
    thread_key = f"{primary_symbol}|{primary_category}"

    # 计算过期时间
    retention_hours = _scorer_config.config.get('retention_hours', 48)
    ts_detected = now_ms()
    expires_at = ts_detected + retention_hours * 3600 * 1000

    return Event(
        id=event_id,
        ts_detected_utc=ts_detected,
        ts_published_utc=ts_published,
        headline=headline,
        source=source_id,
        link=link,
        market="us",
        symbols=symbols,
        categories=categories,
        tags=tags,
        score=score,
        pushed=0,
        expires_at_utc=expires_at,
        thread_key=thread_key
    )


async def _should_notify(event: Event, db: aiosqlite.Connection) -> bool:
    """
    判断是否应该推送通知

    参数:
        event: 事件对象
        db: 数据库连接

    返回:
        是否应该推送
    """
    # 检查分数阈值
    important_threshold = _scorer_config.config.get('important_threshold', 70)
    if event.score < important_threshold:
        return False

    # 检查去重节流
    dedupe_minutes = _scorer_config.config.get('dedupe_minutes', 15)

    # 检查是否存在最近的同主题事件
    if await exists_recent_thread(db, event.thread_key, dedupe_minutes):
        # 检查是否是更高分数的升级推送
        critical_threshold = _scorer_config.config.get('critical_threshold', 85)
        if event.score >= critical_threshold:
            print(f"[scorer] 升级推送: {event.headline[:50]}... (score={event.score})")
            return True
        else:
            print(f"[scorer] 节流跳过: {event.headline[:50]}... (score={event.score})")
            return False

    return True


async def run_scorer(q_in: asyncio.Queue, q_out: asyncio.Queue, db: aiosqlite.Connection) -> None:
    """
    从q_in读取原始事件dict -> 打分/标注/去重 -> 入库；若达到重要/特别重要阈值则放入q_out交给通知器

    参数:
        q_in: 输入队列，包含原始事件dict
        q_out: 输出队列，用于通知器
        db: 数据库连接
    """
    print("[scorer] 启动评分器")

    while True:
        try:
            # 热加载配置
            _scorer_config.reload_if_needed()

            # 从队列获取原始事件
            raw_event = await q_in.get()

            # 检查是否过期
            retention_hours = _scorer_config.config.get('retention_hours', 48)
            now = now_ms()
            ts_published = raw_event.get('ts_published', now)

            if now - ts_published > retention_hours * 3600 * 1000:
                print(f"[scorer] 丢弃过期事件: {raw_event.get('headline', '')[:50]}...")
                continue

            # 检查黑名单
            headline = raw_event.get('headline', '')
            source_id = raw_event.get('source_id', '')

            if _check_blacklist(headline, source_id):
                continue

            # 转换为Event对象
            event = _create_event_from_raw(raw_event)

            # 入库
            success = await insert_event(db, event)
            if not success:
                print(f"[scorer] 入库失败或重复: {event.headline[:50]}...")
                continue

            print(f"[scorer] 入库: {event.headline[:50]}... (score={event.score})")

            # 判断是否需要推送
            if await _should_notify(event, db):
                await q_out.put(event)
                print(f"[scorer] 推送通知: {event.headline[:50]}...")

        except asyncio.CancelledError:
            print("[scorer] 评分器已取消")
            break
        except Exception as e:
            print(f"[scorer] 处理事件失败: {e}")


def score_headline_for_test(headline: str) -> Tuple[str, str, float]:
    """
    用于tests/test_all.py：输入一句话，返回(categories_str, tags_str, score)

    参数:
        headline: 标题文本

    返回:
        (categories字符串, tags字符串, 分数)
    """
    # 确保配置已加载
    _scorer_config.reload_if_needed()

    # 提取股票代码
    symbols = _extract_symbols(headline)

    # 匹配关键词
    tier1_keywords, tier2_keywords, tier1_hits, tier2_hits, negative_hits = _match_keywords(headline)

    # 匹配话题
    hashtags = _match_topics(headline)

    # 计算分数
    has_watchlist_symbol = bool(symbols)
    score = _calculate_score(tier1_hits, tier2_hits, negative_hits, has_watchlist_symbol)

    # 构造categories
    all_keywords = tier1_keywords + tier2_keywords
    categories = ';'.join(all_keywords) if all_keywords else 'general'

    # 构造tags
    tags = ';'.join(hashtags) if hashtags else ''

    return categories, tags, score

