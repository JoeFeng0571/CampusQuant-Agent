"""bench/runners/base.py — Runner ABC"""
from __future__ import annotations

from abc import ABC, abstractmethod

from bench.schema import BenchCase, BenchOutput


class Runner(ABC):
    """Runner 接口:对一个 case 返回一个 output"""

    name: str = "base"

    @abstractmethod
    async def run_case(self, case: BenchCase) -> BenchOutput:
        """给定一个 case,跑一次 agent 返回 BenchOutput"""
        raise NotImplementedError

    async def setup(self) -> None:
        """(可选) 初始化 (如 load graph)"""
        pass

    async def teardown(self) -> None:
        """(可选) 清理"""
        pass
