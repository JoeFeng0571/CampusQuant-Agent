#!/usr/bin/env python3
"""
scripts/seed_community.py — 社区种子内容

在数据库中插入 6 条初始帖子，来自"CQ学长"系统账号。
幂等执行：如果帖子已存在则跳过。

用法:
    python scripts/seed_community.py
"""
import sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import asyncio
from loguru import logger

SEED_POSTS = [
    {
        "title": "新人必读：CampusQuant 使用指南",
        "content": (
            "欢迎来到 CampusQuant 校园财商平台！这里有几个快速上手的建议：\n\n"
            "1. 先去「模拟演练」页面，用模拟资金买入你的第一只股票（推荐从贵州茅台 600519 开始）\n"
            "2. 去「个股分析」页面，让 AI 帮你做一次深度分析，看看 9 个 Agent 是怎么协作的\n"
            "3. 用「持仓体检」功能检查你的持仓健康度\n"
            "4. 学习中心有完整的财商课程，从基础到进阶都有\n\n"
            "记住：这里所有交易都是模拟的，不涉及真实资金，放心大胆地学习！\n\n"
            "有任何问题欢迎在这个帖子下面留言 👇"
        ),
        "tag": "learn",
    },
    {
        "title": "A股入门：市盈率(PE)到底怎么看？",
        "content": (
            "很多同学第一次看到 PE 就懵了，其实很简单：\n\n"
            "PE = 股价 / 每股收益(EPS)\n\n"
            "举个例子：\n"
            "- 贵州茅台 PE 约 28，意味着你花 28 块买到 1 块的年利润\n"
            "- 宁德时代 PE 约 35，说明市场对它未来增长预期更高\n"
            "- 工商银行 PE 约 5，估值便宜但增长空间有限\n\n"
            "⚠️ PE 不能跨行业比较！银行 PE=5 不代表比科技股 PE=30 便宜。\n"
            "同行业对比才有意义：比如比较宁德时代和比亚迪的 PE。\n\n"
            "实操建议：在「个股分析」页面搜索任意股票，AI 报告里会自动给出 PE 和行业对比分析。\n\n"
            "大家还想了解哪些财务指标？留言告诉我！"
        ),
        "tag": "learn",
    },
    {
        "title": "我的第一次模拟交易复盘（亏了 3%）",
        "content": (
            "分享一下我上周的模拟交易经历：\n\n"
            "买入：宁德时代 300750，100股 @ 198.50\n"
            "一周后：跌到 192.30，亏了约 3.1%\n\n"
            "复盘反思：\n"
            "1. 没看技术面就追涨买入，当时 RSI 已经 72（超买区域）\n"
            "2. 没设止损，一直拿着等回本\n"
            "3. 仓位太重，100% 资金买了一只股票\n\n"
            "教训：\n"
            "- 买入前一定要用「个股分析」跑一遍 AI 报告\n"
            "- RSI > 70 的时候谨慎追涨\n"
            "- 单只股票仓位不超过 15%（平台风控也会提醒这个）\n\n"
            "虽然是模拟亏损，但学到了很多。大家有类似经历吗？"
        ),
        "tag": "exp",
    },
    {
        "title": "ETF 定投一个月心得",
        "content": (
            "上个月开始在平台上模拟 ETF 定投，记录一下：\n\n"
            "策略：每周一买入沪深300ETF（510300），每次 2000 元\n"
            "一个月下来：4 次买入，平均成本 3.85\n\n"
            "感受：\n"
            "1. 定投真的不用择时，跌了反而开心（成本摊低了）\n"
            "2. 心态比单只股票好很多，不会天天盯盘\n"
            "3. 适合我们学生党，每月固定金额就行\n\n"
            "推荐新手从这几个 ETF 开始：\n"
            "- 沪深300ETF（510300）—— 大盘蓝筹\n"
            "- 中证500ETF（510500）—— 中盘成长\n"
            "- 创业板ETF（159915）—— 科技创新\n\n"
            "学习中心的「投资策略锦囊」里有详细的定投策略讲解，推荐去看看！"
        ),
        "tag": "analysis",
    },
    {
        "title": "警惕！我差点被「AI量化」骗了",
        "content": (
            "上周有人在微信群里推荐一个「AI 量化交易平台」，说月收益 15-30%，我差点信了。\n\n"
            "红旗信号：\n"
            "1. 承诺「稳赚不赔」—— 这世界上没有无风险高收益\n"
            "2. 要求先充值 5000 元「激活账户」—— 正规券商开户是免费的\n"
            "3. 让你下载一个不知名 APP —— 不是正规应用商店的\n"
            "4. 群里全是「老师」和「托」在晒收益截图\n\n"
            "如何验证平台是否正规：\n"
            "- 去证监会官网 www.csrc.gov.cn 查询是否有牌照\n"
            "- 正规券商只有几十家，名单都是公开的\n"
            "- CampusQuant 这样的模拟平台明确标注「不连接真实交易所」\n\n"
            "学习中心有一篇「大学生防骗指南」，强烈推荐新同学去看。\n"
            "遇到类似情况一定不要转账！"
        ),
        "tag": "risk",
    },
    {
        "title": "港股和美股有什么区别？新手该选哪个？",
        "content": (
            "最近有同学问我港股和美股的区别，整理一下：\n\n"
            "| 对比项 | 港股 | 美股 |\n"
            "| 交易时间 | 9:30-16:00（北京时间） | 21:30-04:00（冬令时） |\n"
            "| 交易制度 | T+0（当天可买卖） | T+0（当天可买卖） |\n"
            "| 最小单位 | 1 手（每手股数不同） | 1 股 |\n"
            "| 涨跌幅 | 无限制 | 无限制 |\n"
            "| 货币 | 港元 HKD | 美元 USD |\n\n"
            "新手建议：\n"
            "1. 如果对科技股感兴趣 → 美股（AAPL、NVDA、TSLA）\n"
            "2. 如果想买中概股 → 港股（腾讯、阿里、小米）\n"
            "3. 先在 CampusQuant 的模拟账户里体验一下！\n\n"
            "平台支持 A 股、港股、美股三个市场，可以都试试看哪个适合自己。"
        ),
        "tag": "learn",
    },
]


async def seed():
    from db.engine import get_db
    from db.models import CommunityPost, User
    from sqlalchemy import select, func

    async for db in get_db():
        # 确保有系统用户
        result = await db.execute(select(User).where(User.username == "CQ学长"))
        sys_user = result.scalar_one_or_none()
        if not sys_user:
            sys_user = User(username="CQ学长", email="mentor@campusquant.store", hashed_password="!system_seed_no_login!")
            db.add(sys_user)
            await db.flush()
            logger.info(f"创建系统用户 CQ学长 (id={sys_user.id})")

        # 检查是否已有种子帖子
        count = await db.execute(select(func.count(CommunityPost.id)).where(CommunityPost.user_id == sys_user.id))
        existing = count.scalar()
        if existing >= len(SEED_POSTS):
            logger.info(f"种子帖子已存在 ({existing} 条)，跳过")
            return

        for post_data in SEED_POSTS:
            # 检查标题是否已存在
            exists = await db.execute(
                select(CommunityPost.id).where(CommunityPost.title == post_data["title"])
            )
            if exists.scalar_one_or_none():
                continue

            post = CommunityPost(
                user_id=sys_user.id,
                title=post_data["title"],
                content=post_data["content"],
                tag=post_data["tag"],
                like_count=0,
                view_count=0,
            )
            db.add(post)
            logger.info(f"添加种子帖子: {post_data['title'][:30]}...")

        await db.commit()
        logger.info(f"社区种子内容添加完成")


if __name__ == "__main__":
    asyncio.run(seed())
