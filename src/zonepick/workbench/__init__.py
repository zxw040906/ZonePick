"""公平评测工作台：固定输入、隔离真值、统一评分、多算法对比。"""

from zonepick.workbench.compare import compare, evaluate, prepare_scenario, apply_algorithm
from zonepick.workbench.noise import NoiseConfig
from zonepick.workbench.splits import SplitConfig

__all__ = [
    "prepare_scenario", "apply_algorithm", "evaluate", "compare",
    "NoiseConfig", "SplitConfig",
]
