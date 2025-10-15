# TODO: 本地dummy数据源生成器
# TODO: 测试数据生成
# TODO: 模拟真实数据结构
# TODO: 随机内容生成
# TODO: 时间序列数据
# TODO: 多语言测试数据

import time
import random
import uuid
from typing import List, Dict


def generate_events(source_id: str) -> List[Dict]:
    """
    生成随机测试事件

    每次返回1-2条随机事件，标题包含不同关键词组合，
    用于测试评分和分类系统

    参数:
        source_id: 数据源ID

    返回:
        事件dict列表
    """
    events = []
    now_ms = int(time.time() * 1000)

    # 关键词模板 - 中英文混合，覆盖不同主题和优先级
    templates = [
        # AI相关
        "NVDA announces major AI upgrade breakthrough in GPU architecture",
        "英伟达发布新一代AI芯片，性能提升50%",
        "OpenAI partnership with Microsoft expands AI training capabilities",
        "谷歌AI部门获得重大技术突破进展",

        # 合同/投资
        "AMD secures $2B contract for datacenter processors",
        "英特尔获得政府芯片制造合同订单",
        "Tesla receives major investment from institutional buyers",
        "苹果公司宣布新的供应链投资计划",

        # 加密货币/RWA
        "BlackRock launches tokenized treasury product for institutional clients",
        "Coinbase announces new custody services for RWA tokens",
        "比特币ETF获得监管机构正式获批",
        "以太坊链上国债代币化项目启动",

        # 事故/负面
        "Major datacenter outage affects cloud services globally",
        "网络安全事故导致交易所暂停服务",
        "Supply chain disruption incident impacts semiconductor production",
        "监管机构对加密货币交易实施新禁令",

        # 财报/业绩
        "TSLA reports strong quarterly earnings, guidance raised",
        "微软财报超预期，云服务收入大增",
        "Meta announces share buyback program worth $10B",
        "亚马逊管理层变更，新CEO上任",

        # 量子计算
        "IBM achieves quantum computing milestone with 1000-qubit processor",
        "谷歌量子计算部门发布新量子芯片",
        "Quantum breakthrough enables faster cryptographic processing",
        "量子计算初创公司完成新一轮融资",

        # 机器人/自动化
        "Boston Dynamics robot demonstrates advanced automation capabilities",
        "特斯拉机器人项目获得重大进展",
        "Industrial automation sensor technology shows promising results",
        "自动化执行器技术在制造业广泛应用"
    ]

    # 随机生成1-2个事件
    num_events = random.randint(1, 2)

    for i in range(num_events):
        headline = random.choice(templates)
        event_id = str(uuid.uuid4())

        event = {
            'headline': headline,
            'link': f'https://example.com/news/{event_id}',
            'ts_published': now_ms,
            'source_id': source_id,
            'raw': {
                'generated': True,
                'template_id': templates.index(headline),
                'created_at': now_ms
            }
        }

        events.append(event)

    return events