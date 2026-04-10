"""bench/runners — 具体 runner 实现"""
from bench.runners.base import Runner
from bench.runners.campusquant import CampusQuantRunner

RUNNERS: dict[str, type[Runner]] = {
    "campusquant": CampusQuantRunner,
    "cq": CampusQuantRunner,  # 别名
}

__all__ = ["Runner", "CampusQuantRunner", "RUNNERS"]
