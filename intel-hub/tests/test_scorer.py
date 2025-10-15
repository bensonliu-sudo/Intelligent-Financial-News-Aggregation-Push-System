# -*- coding: utf-8 -*-
import asyncio
import os
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
from pathlib import Path
from app.models import Event
from app.scorer import load_keywords, load_topics, score_event




def make_ev(h):
    return Event(
        id="t-"+h[:10],
        ts_detected_utc=0,
        ts_published_utc=0,
        headline=h,
        source="unit_test",
        link="",
        market="us",
        symbols="",
        categories="",
        tags="",
        score=0.0,
        pushed=0,
        expires_at_utc=0,
        thread_key="",
    )

def main():
    root = Path(__file__).resolve().parents[1]
    kws = load_keywords(root / "ops/keywords.yml")
    tps = load_topics(root / "ops/topics.yml")

    samples = [
        "NVIDIA announces $2B strategic investment in Intel to expand AI infrastructure",
        "Oracle signs multi-year $1B contract with DoD for cloud services",
        "OpenDoor appoints new CEO and CFO to accelerate growth",
        "Meta launches Ray-Ban smart glasses with AI features",
        "Rumor: Company X to consider partnership with Y on CPO modules",
        "中国启动对半导体产品反倾销调查，或影响高端GPU进口",
    ]

    for h in samples:
        ev = make_ev(h)
        score, words, tags, cats = score_event(ev, kws, tps, bonus_per_extra_group=10)
        print(f"\nHeadline: {h}")
        print(f"Score: {score:.1f}  | hits: {','.join(words)}")
        print(f"Tags: {' '.join(tags)}")
        print(f"Cats: {';'.join(cats)}")

if __name__ == "__main__":
    main()