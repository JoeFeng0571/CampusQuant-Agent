"""
observability/llm_tracker.py — LLM 调用 token 和成本跟踪

在 graph/nodes.py 的 _build_llm() 后插入 callback,
自动记录每次 LLM 调用的 token 消耗和估算成本。

用法 1 — 全局埋点(生产线上):
    from observability.llm_tracker import track_llm_call

    track_llm_call(
        model="qwen-plus",
        node="fundamental_node",
        prompt_tokens=800,
        completion_tokens=1200,
    )

用法 2 — 按实验隔离的 CostTracker (回测/shadow/A-B):
    from observability.llm_tracker import CostTracker, CostExceeded

    tracker = CostTracker(run_id="ab_2026_04_14_baseline", hard_stop_cny=47.0)
    try:
        await tracker.record(
            model="qwen3.5-plus",
            prompt_tokens=800,
            completion_tokens=1200,
        )
    except CostExceeded:
        # 触发 ¥47 硬停,中断当前实验
        ...
    print(f"cumulative: ¥{tracker.total_cny:.2f}")
"""
from __future__ import annotations

import asyncio

from loguru import logger

from observability.metrics import metrics

# ════════════════════════════════════════════════════════════════
# 定价表 — DashScope 2026 Q1 真实单价
# ════════════════════════════════════════════════════════════════
# 单位: 每 1K token 的 CNY
#
# Qwen3.5-Plus 有多个档位(按 context window 大小):
#   0 ~ 128K      : in ¥0.0008 / out ¥0.0048
#   128K ~ 256K   : in ¥0.002  / out ¥0.012
#   256K ~ 1M     : in ¥0.004  / out ¥0.024
# 我们日常 analyze 单次输入 ~31K,输出 ~8K,完全落在 ≤128K 档。
#
# 【v2.2 订正】v2.1 写的 {"in": 0.004, "out": 0.012} 是 256K-1M 大窗口档位,
# 对我们 31K 输入场景多算了 5 倍。改回真实 ≤128K 档位。
_COST_TABLE = {
    "qwen-plus":         {"in": 0.0008, "out": 0.0048},
    "qwen3.5-plus":      {"in": 0.0008, "out": 0.0048},
    "qwen-plus-latest":  {"in": 0.0008, "out": 0.0048},
    # 长上下文档位(256K-1M),本项目用不到但保留供未来
    "qwen-plus-long":    {"in": 0.004,  "out": 0.024},
    # 其他模型
    "qwen-max":          {"in": 0.040,  "out": 0.120},
    "qwen-turbo":        {"in": 0.0003, "out": 0.0006},
    "qwen-turbo-latest": {"in": 0.0003, "out": 0.0006},
    # GPT 系列(如通过代理使用)
    "gpt-4o":            {"in": 0.005,  "out": 0.015},
    "gpt-4o-mini":       {"in": 0.000150, "out": 0.000600},
}

# 未知模型的兜底单价(取 qwen-plus ≤128K 档)
_DEFAULT_COST = {"in": 0.0008, "out": 0.0048}


def _compute_cost_cny(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """按 _COST_TABLE 换算 CNY。未知模型走 _DEFAULT_COST 兜底。"""
    cost_info = _COST_TABLE.get(model, _DEFAULT_COST)
    return (
        prompt_tokens / 1000 * cost_info["in"]
        + completion_tokens / 1000 * cost_info["out"]
    )


# ════════════════════════════════════════════════════════════════
# 生产侧埋点(全局 metrics,不带 per-experiment 累计)
# ════════════════════════════════════════════════════════════════

def track_llm_call(
    model: str,
    node: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int | None = None,
    user_id: str = "",
    thread_id: str = "",
):
    """记录一次 LLM 调用的 token 和成本(全局 metrics,不按实验隔离)"""
    if total_tokens is None:
        total_tokens = prompt_tokens + completion_tokens

    metrics.counter("llm_calls_total", model=model, node=node)
    metrics.histogram("llm_prompt_tokens", prompt_tokens, model=model, node=node)
    metrics.histogram("llm_completion_tokens", completion_tokens, model=model, node=node)
    metrics.histogram("llm_total_tokens", total_tokens, model=model, node=node)

    cost_cny = _compute_cost_cny(model, prompt_tokens, completion_tokens)
    metrics.histogram("llm_cost_cny", cost_cny, model=model, node=node)

    if user_id:
        metrics.counter("llm_cost_by_user", value=cost_cny, user_id=user_id)


# ════════════════════════════════════════════════════════════════
# CostTracker — 按实验隔离的成本累计器
# ════════════════════════════════════════════════════════════════

class CostExceeded(RuntimeError):
    """实验成本超出硬停阈值时抛出。"""
    pass


class CostTracker:
    """
    按 run_id 隔离的 LLM 成本累计器。

    使用场景:
      - A/B 回测: Group A 一个 tracker,Group B 一个 tracker,互不干扰
      - Shadow mode: shadow run 独立 tracker,不污染生产 metrics
      - 本地调试: 起临时 tracker,跑完即抛弃

    接入 LangGraph:
        tracker = CostTracker(run_id="ab_baseline", hard_stop_cny=47.0)
        config = {"configurable": {"cost_tracker": tracker, "thread_id": "..."}}
        await graph.ainvoke(state, config=config)

    节点内:
        tracker = config.get("configurable", {}).get("cost_tracker")
        if tracker and hasattr(raw_resp, "usage_metadata"):
            await tracker.record(
                model=config.DASHSCOPE_MODEL,
                prompt_tokens=raw_resp.usage_metadata.get("input_tokens", 0),
                completion_tokens=raw_resp.usage_metadata.get("output_tokens", 0),
            )
    """

    def __init__(self, run_id: str, hard_stop_cny: float = 95.0):
        self.run_id = run_id
        self.hard_stop = hard_stop_cny
        self._total_cny: float = 0.0
        self._n_calls: int = 0
        self._lock = asyncio.Lock()

    async def record(
        self,
        *,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> float:
        """
        累计一次调用的成本。返回本次调用的 CNY 成本。
        累计总量超过 hard_stop 时抛出 CostExceeded。
        """
        cost = _compute_cost_cny(model, prompt_tokens, completion_tokens)
        async with self._lock:
            self._total_cny += cost
            self._n_calls += 1
            if self._n_calls % 100 == 0:
                avg = self._total_cny / self._n_calls
                logger.info(
                    f"[CostTracker:{self.run_id}] N={self._n_calls}, "
                    f"total=¥{self._total_cny:.2f}, avg=¥{avg:.4f}/call"
                )
            if self._total_cny >= self.hard_stop:
                raise CostExceeded(
                    f"{self.run_id}: ¥{self._total_cny:.2f} >= ¥{self.hard_stop} (硬停)"
                )
        return cost

    def record_sync(
        self,
        *,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> float:
        """同步版本 record(),用于同步代码路径(例如单元测试)。不加锁,单线程使用。"""
        cost = _compute_cost_cny(model, prompt_tokens, completion_tokens)
        self._total_cny += cost
        self._n_calls += 1
        if self._total_cny >= self.hard_stop:
            raise CostExceeded(
                f"{self.run_id}: ¥{self._total_cny:.2f} >= ¥{self.hard_stop} (硬停)"
            )
        return cost

    @property
    def total_cny(self) -> float:
        return self._total_cny

    @property
    def n_calls(self) -> int:
        return self._n_calls

    def reset(self) -> None:
        """重置累计(仅用于测试,生产禁用)。"""
        self._total_cny = 0.0
        self._n_calls = 0
