"""二维圆形目标区域。"""

import numpy as np


def circle_members(positions, center, radius):
    """按水平投影判断区域成员，圆周计入区域。"""
    positions = np.asarray(positions, dtype=float)
    center = np.asarray(center, dtype=float)
    if center.shape != (2,) or not np.isfinite(center).all() or not np.isfinite(radius) or radius <= 0:
        raise ValueError("圆形区域需要有限二维圆心与正半径")
    if positions.ndim != 2 or positions.shape[1] != 3 or not np.isfinite(positions).all():
        raise ValueError("声源坐标须为有限 [S,3]")
    distance = np.linalg.norm(positions[:, :2] - center, axis=1)
    return distance <= radius + 1e-9
