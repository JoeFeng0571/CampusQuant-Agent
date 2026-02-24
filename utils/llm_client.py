"""
LLM 客户端封装
提供统一的 LLM 调用接口，支持 OpenAI 和 Anthropic Claude
"""
import json
from typing import Optional, Dict, Any, List
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from config import config


class LLMClient:
    """LLM 交互客户端，支持多模型切换"""

    def __init__(self, provider: Optional[str] = None, model: Optional[str] = None):
        """
        初始化 LLM 客户端

        Args:
            provider: LLM 提供商 ('openai' 或 'anthropic')，默认使用配置文件设置
            model: 模型名称，默认使用配置文件设置
        """
        self.provider = provider or config.PRIMARY_LLM_PROVIDER
        self.model = model or self._get_default_model()

        # 初始化对应的客户端
        if self.provider == "openai":
            from openai import OpenAI
            self.client = OpenAI(api_key=config.OPENAI_API_KEY)
        elif self.provider == "anthropic":
            from anthropic import Anthropic
            self.client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
        else:
            raise ValueError(f"不支持的 LLM 提供商: {self.provider}")

        logger.info(f"✅ LLM Client 初始化完成: {self.provider} / {self.model}")

    def _get_default_model(self) -> str:
        """获取默认模型"""
        if self.provider == "openai":
            return config.OPENAI_MODEL
        elif self.provider == "anthropic":
            return config.ANTHROPIC_MODEL
        return "gpt-4-turbo-preview"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True
    )
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        response_format: Optional[str] = None,  # "json" 或 None
    ) -> str:
        """
        生成文本响应

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            temperature: 温度参数 (0-1)
            max_tokens: 最大生成 token 数
            response_format: 响应格式，"json" 表示要求 JSON 输出

        Returns:
            生成的文本内容
        """
        try:
            if self.provider == "openai":
                return self._generate_openai(
                    prompt, system_prompt, temperature, max_tokens, response_format
                )
            elif self.provider == "anthropic":
                return self._generate_anthropic(
                    prompt, system_prompt, temperature, max_tokens, response_format
                )
        except Exception as e:
            logger.error(f"❌ LLM 生成失败: {e}")
            raise

    def _generate_openai(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: float,
        max_tokens: int,
        response_format: Optional[str],
    ) -> str:
        """调用 OpenAI API"""
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": prompt})

        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # 如果需要 JSON 格式
        if response_format == "json":
            kwargs["response_format"] = {"type": "json_object"}

        response = self.client.chat.completions.create(**kwargs)
        return response.choices[0].message.content

    def _generate_anthropic(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: float,
        max_tokens: int,
        response_format: Optional[str],
    ) -> str:
        """调用 Anthropic Claude API"""
        # Claude 的 system 是单独参数
        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }

        if system_prompt:
            kwargs["system"] = system_prompt

        # Claude 需要在 prompt 中明确要求 JSON 格式
        if response_format == "json":
            kwargs["messages"][0]["content"] = (
                f"{prompt}\n\n请以 JSON 格式返回结果。"
            )

        response = self.client.messages.create(**kwargs)
        return response.content[0].text

    def generate_structured(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        生成结构化 JSON 响应

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            schema: 期望的 JSON schema (用于提示 LLM)

        Returns:
            解析后的 JSON 对象
        """
        # 构建包含 schema 的提示
        enhanced_prompt = prompt
        if schema:
            enhanced_prompt += f"\n\n请严格按照以下 JSON Schema 返回结果:\n{json.dumps(schema, ensure_ascii=False, indent=2)}"

        response_text = self.generate(
            prompt=enhanced_prompt,
            system_prompt=system_prompt,
            temperature=0.3,  # 降低温度以提高结构化输出稳定性
            response_format="json",
        )

        try:
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON 解析失败: {e}\n原始响应: {response_text}")
            # 尝试提取 JSON
            return self._extract_json_from_text(response_text)

    def _extract_json_from_text(self, text: str) -> Dict[str, Any]:
        """从文本中提取 JSON（应对 LLM 返回额外说明文字的情况）"""
        import re

        # 尝试匹配 JSON 代码块
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(1))

        # 尝试匹配纯 JSON
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))

        # 如果都失败，返回错误信息
        return {"error": "无法解析 JSON", "raw_text": text}

    def analyze_sentiment(self, text: str) -> Dict[str, Any]:
        """
        情感分析快捷方法

        Args:
            text: 待分析文本

        Returns:
            包含情感得分和关键词的字典
        """
        prompt = f"""
请对以下金融文本进行情感分析，并以 JSON 格式返回结果：

文本内容:
{text}

返回格式:
{{
    "sentiment_score": <-1到1之间的浮点数，-1极度负面，0中性，1极度正面>,
    "sentiment_label": "<positive/neutral/negative>",
    "confidence": <0到1之间的置信度>,
    "key_entities": ["实体1", "实体2", ...],
    "reasoning": "简要分析原因"
}}
"""
        system_prompt = "你是一位专业的金融舆情分析师，擅长从新闻、社交媒体中提取市场情绪。"

        return self.generate_structured(
            prompt=prompt,
            system_prompt=system_prompt,
        )

    def explain_decision(
        self,
        context: Dict[str, Any],
        recommendation: str,
    ) -> str:
        """
        解释交易决策（CoT - Chain of Thought）

        Args:
            context: 包含市场数据、指标等的上下文信息
            recommendation: 推荐的交易动作

        Returns:
            决策推理过程
        """
        prompt = f"""
作为一名资深基金经理，请基于以下市场情报，详细解释为什么做出"{recommendation}"的决策：

【上下文信息】
{json.dumps(context, ensure_ascii=False, indent=2)}

【任务】
1. 分析各项指标的含义
2. 解释它们之间的相互作用
3. 说明为什么选择这个决策
4. 指出主要风险点

请使用专业但简洁的语言，分步骤说明你的推理过程。
"""
        system_prompt = "你是一位拥有20年经验的量化交易专家和基金经理。"

        return self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.7,
        )


# ==================== 测试代码 ====================
if __name__ == "__main__":
    # 测试 LLM 客户端
    logger.add("logs/llm_test.log", rotation="10 MB")

    try:
        client = LLMClient()

        # 测试基本生成
        print("\n=== 测试基本文本生成 ===")
        response = client.generate(
            prompt="请用一句话解释什么是量化交易。",
            system_prompt="你是一位金融专家。",
        )
        print(response)

        # 测试情感分析
        print("\n=== 测试情感分析 ===")
        sentiment = client.analyze_sentiment(
            "美联储宣布降息50个基点，市场情绪高涨，纳斯达克指数飙升3%。"
        )
        print(json.dumps(sentiment, ensure_ascii=False, indent=2))

    except Exception as e:
        logger.error(f"测试失败: {e}")
