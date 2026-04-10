"""
observability/llm_tracker.py — LLM 调用 token 和成本跟踪

在 graph/nodes.py 的 _build_llm() 后插入 callback,
自动记录每次 LLM 调用的 token 消耗和估算成本。

用法:
    from observability.llm_tracker import track_llm_call

    # 在 LLM 调用后
    track_llm_call(
        model="qwen-plus",
        node="fundamental_node",
        prompt_tokens=800,
        completion_tokens=1200,
    )
"""
from __future__ import annotations

from observability.metrics import metrics

# 千 token 价格 (CNY) — 按 DashScope 官网 2026 Q1
_COST_TABLE = {
    "qwen-plus":     {"in": 0.004, "out": 0.012},
    "qwen-max":      {"in": 0.040, "out": 0.120},
    "qwen-turbo":    {"in": 0.002, "out": 0.006},
    "qwen3.5-plus":  {"in": 0.004, "out": 0.012},
    # GPT (通过代理,价格可能不同)
    "gpt-4o":        {"in": 0.005, "out": 0.015},
    "gpt-4o-mini":   {"in": 0.000150, "out": 0.000600},
}


def track_llm_call(
    model: str,
    node: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int | None = None,
    user_id: str = "",
    thread_id: str = "",
):
    """记录一次 LLM 调用的 token 和成本"""
    if total_tokens is None:
        total_tokens = prompt_tokens + completion_tokens

    metrics.counter("llm_calls_total", model=model, node=node)
    metrics.histogram("llm_prompt_tokens", prompt_tokens, model=model, node=node)
    metrics.histogram("llm_completion_tokens", completion_tokens, model=model, node=node)
    metrics.histogram("llm_total_tokens", total_tokens, model=model, node=node)

    # 成本估算
    cost_info = _COST_TABLE.get(model, {"in": 0.004, "out": 0.012})
    cost_cny = (
        prompt_tokens / 1000 * cost_info["in"]
        + completion_tokens / 1000 * cost_info["out"]
    )
    metrics.histogram("llm_cost_cny", cost_cny, model=model, node=node)

    if user_id:
        metrics.counter("llm_cost_by_user", value=cost_cny, user_id=user_id)
