"""
bench/judges/llm_judge.py — LLM-as-Judge 评分器

使用 LLM 对 (case, output) 评分。支持 Qwen / GPT / Claude 任意 OpenAI 兼容 API。

评分维度 (4 个,每个 1-5):
  1. grounding      是否引用具体数字
  2. coverage       是否覆盖 key_points
  3. reasoning      论据逻辑合理性
  4. risk_awareness 是否提及 risk_points

额外:
  - direction_match 二元 (BUY/HOLD/SELL 是否一致)
  - failure_modes   tag list
"""
from __future__ import annotations

import json
import re
from typing import Any

from loguru import logger

from bench.schema import BenchCase, BenchOutput, BenchScore


_RUBRIC_PROMPT = """你是资深投资研究员,正在评估一个 AI 投顾系统对某只股票的建议质量。

【Case 信息】
股票: {symbol} ({name})
市场: {market}
预期方向 (人工标注): {expected_direction}

【人工标注的关键论点】(AI 输出应该覆盖尽量多这些点)
{key_points}

【人工标注的风险点】(AI 输出应该提及的风险)
{risk_points}

【人工分析师概述】
{analyst_notes}

──────────────────────────────────────────────
【AI 系统输出】

方向: {ai_direction}
置信度: {ai_confidence}

基本面摘要:
{fundamental_summary}

技术面摘要:
{technical_summary}

情绪面摘要:
{sentiment_summary}

最终决策理由:
{rationale}
──────────────────────────────────────────────

请从 4 个维度对这份 AI 输出打分(每个 1-5 分):

1. **grounding** (数据引用): AI 是否引用了具体数字、事实、财报数据?
   - 1 = 全是"建议关注基本面"这种废话
   - 3 = 有 1-2 个具体数字
   - 5 = 多处引用具体 PE/营收/增长率等

2. **coverage** (覆盖度): AI 输出覆盖了多少上面列出的 key_points?
   - 1 = 0% 覆盖
   - 3 = 30-60% 覆盖
   - 5 = 80%+ 覆盖

3. **reasoning** (论据质量): AI 的推理逻辑是否严谨?
   - 1 = 逻辑混乱/自相矛盾
   - 3 = 逻辑合理但浅
   - 5 = 论据链条清晰、层次分明

4. **risk_awareness** (风险提示): AI 是否识别并提及了 risk_points 里的风险?
   - 1 = 完全没提风险
   - 3 = 提到 1 个
   - 5 = 提到多数风险点

【额外评估】
- direction_match: AI 方向与预期方向是否一致 (true/false)
- failure_modes: 如有问题,用 tag 列出,如 ["空泛","数字编造","逻辑矛盾","缺少风险提示","偏乐观"]

请严格以下面 JSON 格式输出 (仅 JSON,不要其他文字):

{{
    "grounding_score": <1-5>,
    "coverage_score": <1-5>,
    "reasoning_score": <1-5>,
    "risk_awareness_score": <1-5>,
    "direction_match": <true|false>,
    "failure_modes": ["tag1", "tag2"],
    "comment": "1-2 句话总评"
}}
"""


class LLMJudge:
    def __init__(self, model: str = "qwen-plus", name: str | None = None):
        """
        Args:
            model: DashScope 兼容的模型名 (qwen-plus / qwen-max / qwen-turbo)
            name:  judge 的显示名,默认 = model
        """
        self.model = model
        self.name = name or model
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client

        from config import config
        from langchain_openai import ChatOpenAI

        self._client = ChatOpenAI(
            model=self.model,
            api_key=config.DASHSCOPE_API_KEY,
            base_url=config.DASHSCOPE_BASE_URL,
            temperature=0.1,  # 评分要稳定
            max_tokens=800,
        )
        return self._client

    async def score(self, case: BenchCase, output: BenchOutput) -> BenchScore:
        """给一个 case + output 打分"""
        # 如果 runner 崩了,直接给最低分
        if output.failed:
            return BenchScore(
                case_id=case.id,
                runner_name=output.runner_name,
                judge_name=self.name,
                direction_match=False,
                grounding_score=1,
                coverage_score=1,
                reasoning_score=1,
                risk_awareness_score=1,
                judge_comment=f"Runner 崩溃: {output.error}",
                failure_modes=["runner_crash"],
            )

        prompt = _RUBRIC_PROMPT.format(
            symbol=case.symbol,
            name=case.name,
            market=case.market,
            expected_direction=case.expected_direction,
            key_points="\n".join(f"  - {p}" for p in case.key_points),
            risk_points="\n".join(f"  - {p}" for p in case.risk_points),
            analyst_notes=case.analyst_notes,
            ai_direction=output.direction,
            ai_confidence=f"{output.confidence:.2f}",
            fundamental_summary=output.fundamental_summary or "(无)",
            technical_summary=output.technical_summary or "(无)",
            sentiment_summary=output.sentiment_summary or "(无)",
            rationale=output.rationale or "(无)",
        )

        try:
            client = self._get_client()
            resp = await client.ainvoke(prompt)
            raw = resp.content if hasattr(resp, "content") else str(resp)
            parsed = _extract_json(raw)

            return BenchScore(
                case_id=case.id,
                runner_name=output.runner_name,
                judge_name=self.name,
                direction_match=bool(parsed.get("direction_match", False)),
                grounding_score=_clamp_1_5(parsed.get("grounding_score", 1)),
                coverage_score=_clamp_1_5(parsed.get("coverage_score", 1)),
                reasoning_score=_clamp_1_5(parsed.get("reasoning_score", 1)),
                risk_awareness_score=_clamp_1_5(parsed.get("risk_awareness_score", 1)),
                judge_comment=str(parsed.get("comment", ""))[:400],
                failure_modes=[str(x) for x in parsed.get("failure_modes", [])],
            )

        except Exception as e:
            logger.error(f"[LLMJudge] {case.id} 评分失败: {e}")
            return BenchScore(
                case_id=case.id,
                runner_name=output.runner_name,
                judge_name=self.name,
                direction_match=output.direction == case.expected_direction,
                grounding_score=1,
                coverage_score=1,
                reasoning_score=1,
                risk_awareness_score=1,
                judge_comment=f"Judge 调用失败: {e}",
                failure_modes=["judge_error"],
            )


def _extract_json(text: str) -> dict[str, Any]:
    """从 LLM 输出里抽出 JSON, 容错 markdown code block"""
    # 去掉 ```json ``` 包裹
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    # 直接尝试
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 抓第一个 { ... } 块
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass

    logger.warning(f"无法解析 JSON: {text[:200]}")
    return {}


def _clamp_1_5(v: Any) -> int:
    """把任意输入 clamp 到 1-5 整数"""
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return 1
    return max(1, min(5, n))
