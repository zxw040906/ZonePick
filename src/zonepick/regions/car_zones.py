"""Four fixed cabin zones in the project coordinate system."""

from dataclasses import dataclass

import numpy as np

ZONE_ORDER = ("FL", "FR", "RL", "RR")


@dataclass(frozen=True)
class CarZones:
    dimensions: tuple
    dividers: tuple
    representatives: tuple

    def check_point(self, position):
        point = np.asarray(position, dtype=float)
        if (point.shape != (3,) or not np.isfinite(point).all()
                or np.any(point <= 0) or np.any(point >= self.dimensions)):
            raise ValueError("Position must be strictly inside the cabin")
        return tuple(map(float, point))

    def zone_id(self, position):
        x, y, _ = self.check_point(position)
        x_split, y_split = self.dividers
        return ZONE_ORDER[2 * (y >= y_split) + (x >= x_split)]

    def bounds(self, zone_id):
        index = ZONE_ORDER.index(zone_id)
        x_split, y_split = self.dividers
        xs = (0.0, x_split, self.dimensions[0])
        ys = (0.0, y_split, self.dimensions[1])
        row, column = divmod(index, 2)
        return ((xs[column], ys[row], 0.0), (xs[column + 1], ys[row + 1], self.dimensions[2]))

    def representative(self, zone_id):
        return self.representatives[ZONE_ORDER.index(zone_id)]

    @staticmethod
    def members(zone_ids):
        return tuple(tuple(i for i, label in enumerate(zone_ids) if label == z) for z in ZONE_ORDER)
