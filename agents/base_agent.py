"""
智能体基类
定义所有 Agent 的公共接口和行为
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from loguru import logger

from utils import LLMClient


class BaseAgent(ABC):
    """智能体抽象基类"""

    def __init__(self, name: str, llm_client: Optional[LLMClient] = None):
        """
        初始化智能体

        Args:
            name: 智能体名称
            llm_client: LLM 客户端实例（可选，如果不提供则自动创建）
        """
        self.name = name
        self.llm_client = llm_client or LLMClient()
        logger.info(f"🤖 {self.name} 初始化完成")

    @abstractmethod
    def analyze(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析方法（子类必须实现）

        Args:
            symbol: 交易标的代码
            data: 输入数据

        Returns:
            分析结果字典
        """
        pass

    @abstractmethod
    def get_system_prompt(self) -> str:
        """
        获取该智能体的系统提示词（子类必须实现）

        Returns:
            系统提示词字符串
        """
        pass

    def get_recommendation(self, analysis_result: Dict[str, Any]) -> str:
        """
        从分析结果中提取推荐意见

        Args:
            analysis_result: 分析结果

        Returns:
            推荐操作 ('BUY', 'SELL', 'HOLD')
        """
        if "recommendation" in analysis_result:
            return analysis_result["recommendation"]
        return "HOLD"

    def get_confidence(self, analysis_result: Dict[str, Any]) -> float:
        """
        从分析结果中提取置信度

        Args:
            analysis_result: 分析结果

        Returns:
            置信度 (0-1)
        """
        if "confidence" in analysis_result:
            return float(analysis_result["confidence"])
        return 0.5

    def log_analysis(self, symbol: str, result: Dict[str, Any]):
        """
        记录分析结果

        Args:
            symbol: 交易标的
            result: 分析结果
        """
        recommendation = self.get_recommendation(result)
        confidence = self.get_confidence(result)

        logger.info(
            f"📊 {self.name} | {symbol} | "
            f"推荐: {recommendation} | 置信度: {confidence:.2f}"
        )

    def format_report(self, analysis_result: Dict[str, Any]) -> str:
        """
        格式化分析报告为可读文本

        Args:
            analysis_result: 分析结果

        Returns:
            格式化的报告文本
        """
        report = f"\n{'='*60}\n"
        report += f"📋 {self.name} 分析报告\n"
        report += f"{'='*60}\n"

        for key, value in analysis_result.items():
            if isinstance(value, dict):
                report += f"{key}:\n"
                for sub_key, sub_value in value.items():
                    report += f"  - {sub_key}: {sub_value}\n"
            elif isinstance(value, list):
                report += f"{key}:\n"
                for item in value:
                    report += f"  - {item}\n"
            else:
                report += f"{key}: {value}\n"

        report += f"{'='*60}\n"
        return report
