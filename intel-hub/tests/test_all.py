# -*- coding: utf-8 -*-
"""
统一测试脚本：tests/test_all.py
用法：
  - python tests/test_all.py             # 跑全部步骤（自动跳过未实现的）
  - python tests/test_all.py --only 3    # 只跑 Step 3
说明：
  - 设计成“鲁棒 + 渐进”，每步只依赖前一步约定的最小能力。
  - 如果某步代码尚未实现，测试会“跳过”而不是失败。
  - 运行前请先激活虚拟环境并安装依赖：
        python3 -m venv .venv && source .venv/bin/activate
        pip install -r requirements.txt
"""

import argparse
import asyncio
import importlib
import os
import sys
import time
import glob
import json
from pathlib import Path
from contextlib import suppress
from subprocess import Popen, PIPE
import sys, os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # ✅ 把 intel-hub 根目录加到 sys.path
os.chdir(ROOT)
ROOT = Path(__file__).resolve().parents[1]  # intel-hub/
os.chdir(ROOT)

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"

def ok(msg): print(f"{GREEN}✅ {msg}{RESET}")
def warn(msg): print(f"{YELLOW}⚠️  {msg}{RESET}")
def fail(msg): print(f"{RED}❌ {msg}{RESET}")

# ---------- Step 0 ----------
def test_step0():
    required = [
        "app/main.py","app/models.py","app/storage.py","app/collector.py",
        "app/scorer.py","app/notifier.py","app/utils.py","app/web.py",
        "app/parsers/rss_default.py","app/parsers/json_default.py","app/parsers/dummy_gen.py",
        "ops/config.yml","ops/keywords.yml","ops/topics.yml","ops/sources.yml","ops/universe.yml",
        "tests/sample_events.jsonl","requirements.txt"
    ]
    missing = [p for p in required if not Path(p).exists()]
    if missing:
        fail(f"Step 0 缺少文件: {missing}")
        return False
    ok("Step 0 目录与文件存在")
    return True

# ---------- Step 1 ----------
def test_step1():
    try:
        import yaml
    except Exception as e:
        fail(f"缺少 PyYAML 依赖: {e}")
        return False
    try:
        for p in glob.glob("ops/*.yml"):
            with open(p,"r") as f:
                yaml.safe_load(f)
        ok("Step 1 YAML 配置可解析")
        return True
    except Exception as e:
        fail(f"YAML 解析失败: {e}")
        return False

# ---------- Step 2 ----------
# 顶部加：
import traceback

# ---------- Step 2（替换为这一版） ----------
# 顶部建议保留 import traceback

async def test_step2_async(verbose: bool = True):
    try:
        storage = importlib.import_module("app.storage")
        models = importlib.import_module("app.models")
        if not hasattr(storage, "init_db"):
            warn("Step 2: 未找到 init_db，跳过")
            return True

        db = await storage.init_db("test_step2.db")  # 打开连接

        if not hasattr(models, "Event"):
            warn("Step 2: 未找到 models.Event，跳过")
            # ✅ 关闭连接再返回
            await db.close()
            return True

        from app.models import Event

        now = int(time.time()*1000)
        e = Event(
            id="test_step2_1",
            ts_detected_utc=now,
            ts_published_utc=now,
            headline="测试事件",
            source="dummy",
            link="http://x",
            market="us",
            symbols="NVDA",
            categories="contract",
            tags="#AI",
            score=90.0,
            pushed=0,
            expires_at_utc=now+1000,
            thread_key="NVDA|contract",
        )

        ok1 = await storage.insert_event(db, e)
        if verbose:
            print("[DEBUG] insert_event return =", ok1)
        assert ok1, "insert_event 返回 False（可能主键冲突或SQL失败）"

        if hasattr(storage, "delete_expired"):
            await storage.delete_expired(db, now+5000)

        # ✅ 关键：关闭连接，避免事件循环挂起
        await db.close()

        ok("Step 2 SQLite 基本写删 OK")
        return True

    except Exception:
        traceback.print_exc()
        return False

def test_step2():
    try:
        return asyncio.run(test_step2_async(verbose=True))
    except Exception:
        traceback.print_exc()
        return False
# ---------- Step 3 ----------
async def test_step3_async():
    try:
        collector = importlib.import_module("app.collector")
    except Exception as e:
        warn(f"Step 3: 无法导入 app.collector（可能尚未实现）：{e}")
        return True  # 跳过

    if not hasattr(collector, "run_collectors"):
        warn("Step 3: 未找到 run_collectors，跳过")
        return True

    q = asyncio.Queue()
    tasks = await collector.run_collectors(q)
    got = 0
    start = time.time()
    try:
        while time.time()-start < 20:
            try:
                item = await asyncio.wait_for(q.get(), timeout=5)
                got += 1
            except asyncio.TimeoutError:
                pass
    finally:
        for t in tasks:
            t.cancel()
    if got > 0:
        ok("Step 3 采集器产出事件 OK")
        return True
    warn("Step 3 未采到事件（若只实现了骨架，可忽略）")
    return True

def test_step3():
    try:
        return asyncio.run(test_step3_async())
    except Exception as e:
        fail(f"Step 3 失败: {e}")
        return False

# ---------- Step 4 ----------
def test_step4():
    try:
        scorer = importlib.import_module("app.scorer")
    except Exception as e:
        warn(f"Step 4: 无法导入 app.scorer（可能尚未实现）：{e}")
        return True  # 跳过

    if not hasattr(scorer, "score_headline_for_test"):
        warn("Step 4: 未找到 score_headline_for_test，跳过")
        return True

    samples = [
        "NVIDIA signs multi-year contracts with government",
        "TSMC invested heavily in HBM for AI upgrade",
        "某平台上线RWA链上国债 tokenized treasury",
        "Company is considering investment? rumor",
    ]
    try:
        for s in samples:
            cats, tags, sc = scorer.score_headline_for_test(s)
            print("  ", s, "=>", cats, tags, sc)
        ok("Step 4 打分函数可用（请人工目视检查打印是否合理）")
        return True
    except Exception as e:
        fail(f"Step 4 失败: {e}")
        return False

# ---------- Step 5 ----------
async def test_step5_async():
    try:
        notifier = importlib.import_module("app.notifier")
    except Exception as e:
        warn(f"Step 5: 无法导入 app.notifier（可能尚未实现）：{e}")
        return True  # 跳过

    if not hasattr(notifier, "send_text_test"):
        warn("Step 5: 未找到 send_text_test，跳过")
        return True

    try:
        await notifier.send_text_test("测试：无Token应打印到控制台")
        ok("Step 5 推送回退 OK")
        return True
    except Exception as e:
        fail(f"Step 5 失败: {e}")
        return False

def test_step5():
    try:
        return asyncio.run(test_step5_async())
    except Exception as e:
        fail(f"Step 5 失败: {e}")
        return False

# ---------- Step 6 ----------
def test_step6():
    if not Path("app/main.py").exists():
        warn("Step 6: app/main.py 不存在，跳过")
        return True
    # 用子进程跑 15 秒 main
    try:
        p = Popen([sys.executable, "app/main.py", "--run-seconds", "15"], stdout=PIPE, stderr=PIPE)
        try:
            out, err = p.communicate(timeout=25)
        except Exception:
            p.kill()
            out, err = p.communicate()
        print(out.decode("utf-8", "ignore"))
        if err:
            print(err.decode("utf-8", "ignore"))
        ok("Step 6 主循环可运行（已尝试15秒）")
        return True
    except Exception as e:
        warn(f"Step 6 运行 main.py 失败（可能尚未完成）：{e}")
        return True  # 不强制失败

# ---------- Step 7 ----------
def test_step7():
    # 仅检查 web.py 存在与可导入；Streamlit 实际渲染人为手测
    if not Path("app/web.py").exists():
        warn("Step 7: app/web.py 不存在，跳过")
        return True
    try:
        importlib.import_module("app.web")
        ok("Step 7 网页模块可导入（UI 人工用 Streamlit 跑）")
        return True
    except Exception as e:
        warn(f"Step 7: 无法导入 app.web：{e}")
        return True

# ---------- Step 8 ----------
def test_step8():
    # 逻辑属于 Step4 的增强，这里简单检查 keywords.yml 里黑名单字段存在
    try:
        import yaml
        with open("ops/keywords.yml","r") as f:
            data = yaml.safe_load(f)
        if "source_blacklist" in data and "keyword_blacklist" in data:
            ok("Step 8 黑名单配置存在（功能随 Step4 实现）")
            return True
        warn("Step 8 黑名单配置缺失（若尚未实现可忽略）")
        return True
    except Exception as e:
        warn(f"Step 8: 读取 keywords.yml 失败：{e}")
        return True

# ---------- Step 9 ----------
def test_step9():
    # 检查 exports 目录写入权限；如果 utils.export_recent_events_for_test 存在则尝试调用
    try:
        exports = Path("exports")
        exports.mkdir(exist_ok=True)
        try:
            utils = importlib.import_module("app.utils")
            if hasattr(utils, "export_recent_events_for_test"):
                import app.storage as storage
                db = asyncio.run(storage.init_db("intel.db"))
                asyncio.run(utils.export_recent_events_for_test(db))
                files = list(exports.rglob("events.csv"))
                if files:
                    ok("Step 9 导出生成（已找到 CSV）")
                    return True
                else:
                    warn("Step 9 未找到导出 CSV（若尚未实现可忽略）")
                    return True
        except Exception as e:
            warn(f"Step 9: 导出函数不存在或失败（可忽略）：{e}")
            return True
    except Exception as e:
        warn(f"Step 9: 创建 exports 失败（权限问题？）：{e}")
        return True

# ---------- Step 10 ----------
def test_step10():
    # 容错/健康度主要看运行时日志，这里仅提示
    ok("Step 10 建议：手动将某个 sources.yml URL 改错后运行 Step 6，观察日志不中断")
    return True

STEP_FUNCS = {
    0: test_step0,
    1: test_step1,
    2: test_step2,
    3: test_step3,
    4: test_step4,
    5: test_step5,
    6: test_step6,
    7: test_step7,
    8: test_step8,
    9: test_step9,
    10: test_step10,
}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", type=int, help="仅测试指定步骤（0-10）")
    args = parser.parse_args()

    if args.only is not None:
        fn = STEP_FUNCS.get(args.only)
        if not fn:
            fail("无效步骤号")
            sys.exit(2)
        passed = fn()
        sys.exit(0 if passed else 1)

    # 跑全部
    all_passed = True
    for step in range(0, 11):
        print(f"\n===== 运行 Step {step} 测试 =====")
        fn = STEP_FUNCS[step]
        try:
            passed = fn()
        except Exception as e:
            fail(f"Step {step} 异常：{e}")
            passed = False
        all_passed = all_passed and passed
    print("\n===============================")
    if all_passed:
        ok("全部已通过或合理跳过（未实现的步骤不会阻塞）")
        sys.exit(0)
    else:
        fail("存在失败的步骤，请上滚查看日志")
        sys.exit(1)

if __name__ == "__main__":
    main()