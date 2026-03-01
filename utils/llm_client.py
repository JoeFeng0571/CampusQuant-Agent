"""
LLM 客户端封装
提供统一的 LLM 调用接口，默认使用阿里云百炼（DashScope/Qwen），
备选支持 OpenAI 和 Anthropic Claude。
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
            provider: LLM 提供商 ('dashscope' | 'openai' | 'anthropic')，默认使用配置文件设置
            model: 模型名称，默认使用配置文件设置
        """
        self.provider = provider or config.PRIMARY_LLM_PROVIDER
        self.model = model or self._get_default_model()

        # 初始化对应的客户端
        if self.provider == "dashscope":
            # DashScope 使用 OpenAI 兼容端点，直接复用 openai SDK
            from openai import OpenAI
            self.client = OpenAI(
                api_key=config.DASHSCOPE_API_KEY,
                base_url=config.DASHSCOPE_BASE_URL,
            )
        elif self.provider == "openai":
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
        if self.provider == "dashscope":
            return config.DASHSCOPE_MODEL
        elif self.provider == "openai":
            return config.OPENAI_MODEL
        elif self.provider == "anthropic":
            return config.ANTHROPIC_MODEL
        return config.DASHSCOPE_MODEL

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
            if self.provider in ("dashscope", "openai"):
                return self._generate_openai_compat(
                    prompt, system_prompt, temperature, max_tokens, response_format
                )
            elif self.provider == "anthropic":
                return self._generate_anthropic(
                    prompt, system_prompt, temperature, max_tokens, response_format
                )
        except Exception as e:
            logger.error(f"❌ LLM 生成失败: {e}")
            raise

    def _generate_openai_compat(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: float,
        max_tokens: int,
        response_format: Optional[str],
    ) -> str:
        """调用 OpenAI 兼容 API（DashScope / OpenAI 均走此路径）"""
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
        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }

        if system_prompt:
            kwargs["system"] = system_prompt

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
        enhanced_prompt = prompt
        if schema:
            enhanced_prompt += f"\n\n请严格按照以下 JSON Schema 返回结果:\n{json.dumps(schema, ensure_ascii=False, indent=2)}"

        response_text = self.generate(
            prompt=enhanced_prompt,
            system_prompt=system_prompt,
            temperature=0.3,
            response_format="json",
        )

        try:
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON 解析失败: {e}\n原始响应: {response_text}")
            return self._extract_json_from_text(response_text)

    def _extract_json_from_text(self, text: str) -> Dict[str, Any]:
        """从文本中提取 JSON（应对 LLM 返回额外说明文字的情况）"""
        import re

        json_match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(1))

        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))

        return {"error": "无法解析 JSON", "raw_text": text}

    def analyze_sentiment(self, text: str) -> Dict[str, Any]:
        """情感分析快捷方法"""
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
        return self.generate_structured(prompt=prompt, system_prompt=system_prompt)

    def explain_decision(self, context: Dict[str, Any], recommendation: str) -> str:
        """解释交易决策（CoT）"""
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
        return self.generate(prompt=prompt, system_prompt=system_prompt, temperature=0.7)


# ==================== 测试代码 ====================
if __name__ == "__main__":
    logger.add("logs/llm_test.log", rotation="10 MB")

    try:
        client = LLMClient()

        print("\n=== 测试基本文本生成 ===")
        response = client.generate(
            prompt="请用一句话解释什么是ETF定投。",
            system_prompt="你是一位面向大学生的财商教育专家。",
        )
        print(response)

        print("\n=== 测试情感分析 ===")
        sentiment = client.analyze_sentiment(
            "A股市场受政策利好提振，沪深300指数单日上涨2.3%，科技板块领涨。"
        )
        print(json.dumps(sentiment, ensure_ascii=False, indent=2))

    except Exception as e:
        logger.error(f"测试失败: {e}")
