"""算法插件包：导入本包即完成所有插件注册。"""

from zonepick.algorithms.base import (
    Algorithm, AlgorithmInput, Region, FORBIDDEN_FIELDS,
    algorithm_names, ensure_no_forbidden_fields, get_algorithm,
    register, registered_classes,
)
# 触发内置算法注册（DAS / MVDR / 未处理基线）。
# 注意：das、mvdr 是新模块（包装/扩展 classical），不能写在 classical/__init__.py 里，
# 否则从 zonepick.algorithms 反向导入会形成循环导入。
from zonepick.algorithms import classical  # noqa: F401
from zonepick.algorithms import das        # noqa: F401
from zonepick.algorithms import mvdr       # noqa: F401
from zonepick.algorithms import identity    # noqa: F401

__all__ = [
    "Algorithm", "AlgorithmInput", "Region", "FORBIDDEN_FIELDS",
    "algorithm_names", "ensure_no_forbidden_fields", "get_algorithm",
    "register", "registered_classes",
]
