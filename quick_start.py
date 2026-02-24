"""
快速启动脚本
用于快速测试系统是否正常工作
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.append(str(Path(__file__).parent))

from loguru import logger
from config import validate_config
from agents import DataAgent, TechnicalAgent

logger.add("logs/quick_start.log", rotation="10 MB")


def test_data_agent():
    """测试数据情报员"""
    print("\n" + "="*60)
    print("🧪 测试 1: 数据情报员")
    print("="*60)

    try:
        agent = DataAgent()
        result = agent.analyze("AAPL", data={"days": 30})

        if result["status"] == "success":
            print("✅ 数据获取成功!")
            print(agent.get_summary(result))
        else:
            print(f"❌ 数据获取失败: {result.get('error')}")

    except Exception as e:
        print(f"❌ 测试失败: {e}")


def test_technical_agent():
    """测试技术分析师"""
    print("\n" + "="*60)
    print("🧪 测试 2: 技术分析师")
    print("="*60)

    try:
        # 先获取数据
        data_agent = DataAgent()
        data_result = data_agent.analyze("AAPL", data={"days": 60})

        if data_result["status"] != "success":
            print("❌ 数据获取失败，无法进行技术分析")
            return

        # 技术分析
        tech_agent = TechnicalAgent()
        tech_result = tech_agent.analyze("AAPL", data=data_result)

        if tech_result["status"] == "success":
            print("✅ 技术分析完成!")
            print(f"推荐: {tech_result.get('recommendation', 'N/A')}")
            print(f"置信度: {tech_result.get('confidence', 0):.2f}")
            print(f"关键因素: {tech_result.get('key_factors', [])}")
        else:
            print(f"❌ 技术分析失败: {tech_result.get('error')}")

    except Exception as e:
        print(f"❌ 测试失败: {e}")


def main():
    """主函数"""
    print("""
    ╔═══════════════════════════════════════════════════════╗
    ║                                                       ║
    ║      🚀 快速启动 - 系统测试                          ║
    ║                                                       ║
    ╚═══════════════════════════════════════════════════════╝
    """)

    # 验证配置
    print("\n📋 步骤 1: 验证配置文件...")
    if not validate_config():
        print("\n❌ 配置验证失败!")
        print("请检查 config.py 和 .env 文件")
        return

    # 测试数据获取
    test_data_agent()

    # 测试技术分析
    test_technical_agent()

    print("\n" + "="*60)
    print("✅ 系统测试完成!")
    print("\n💡 接下来可以运行主程序:")
    print("   python workflow.py")
    print("="*60 + "\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断测试")
    except Exception as e:
        logger.exception(f"测试异常: {e}")
        print(f"\n❌ 测试异常: {e}")
