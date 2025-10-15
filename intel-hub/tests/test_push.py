# test_push.py
import asyncio
import os
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
from app.notifier import _TelegramAdapter   # 确认类名和路径与你的一致

# 在这里填你的真实 token 和 chat_id
TELEGRAM_TOKEN = ""
TELEGRAM_CHAT_ID = ""

async def main():
    tg = _TelegramAdapter(
        token=TELEGRAM_TOKEN,
        chat_id=TELEGRAM_CHAT_ID,
        retry={"max_times": 3, "backoff_sec": 2},
    )

    ok = await tg.send("🔔 测试推送：Intel-Hub notifier is working")
    print("send result =", ok)

    await tg.close()

if __name__ == "__main__":
    asyncio.run(main())