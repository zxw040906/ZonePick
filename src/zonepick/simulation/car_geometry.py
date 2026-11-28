"""Validated cabin geometry shared by the CLI, web and scene builder."""

from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np

from zonepick.regions.car_zones import CarZones, ZONE_ORDER

CONFIG_ROOT = Path(__file__).resolve().parents[3] / "configs"
MIC_IDS = tuple(f"M{i}" for i in range(10))
LAYOUT_SIZES = (8, 6, 4, 3, 2)


@dataclass(frozen=True)
class ArrayLayout:
    array_id: str
    channel_ids: tuple
    microphone_positions: tuple
    reference_channel: int

    def select(self, master):
        master = np.asarray(master)
        if master.ndim < 2 or master.shape[-2] != len(MIC_IDS):
            raise ValueError("Master waveform must have 10 channels in M0–M9 order")
        return np.take(master, [MIC_IDS.index(channel) for channel in self.channel_ids], axis=-2)


@dataclass(frozen=True)
class CarGeometry:
    room_id: str
    zones: CarZones
    seats: tuple
    source_candidates: tuple
    microphones: tuple
    layouts: tuple

    def layout(self, count):
        if type(count) is not int or count not in LAYOUT_SIZES:
            raise ValueError(f"Unsupported microphone count: {count}")
        return self.layouts[LAYOUT_SIZES.index(count)]

    def to_dict(self):
        return {
            "room_id": self.room_id, "status": "provisional_simulation_geometry", "unit": "m",
            "axes": ["left_to_right", "front_to_rear", "floor_to_roof"],
            "dimensions": self.zones.dimensions, "zone_dividers": self.zones.dividers,
            "zone_order": ZONE_ORDER,
            "zones": {zone: {"bounds": self.zones.bounds(zone), "seat": seat,
                             "representative_point": self.zones.representative(zone),
                             "source_candidates": candidates}
                      for zone, seat, candidates in zip(ZONE_ORDER, self.seats, self.source_candidates)},
            "microphones": dict(zip(MIC_IDS, self.microphones)),
            "layouts": {str(size): {"array_id": layout.array_id, "channel_ids": layout.channel_ids,
                                    "microphone_positions": layout.microphone_positions,
                                    "reference_channel": layout.reference_channel}
                        for size, layout in zip(LAYOUT_SIZES, self.layouts)},
        }


def load_car_geometry(geometry_path=None, array_path=None):
    geometry_path = geometry_path or CONFIG_ROOT / "geometry/car_geometry_v0.json"
    array_path = array_path or CONFIG_ROOT / "arrays/car_array_family_v0.json"
    geometry = json.loads(Path(geometry_path).read_text(encoding="utf-8"))
    arrays = json.loads(Path(array_path).read_text(encoding="utf-8"))
    dimensions = np.asarray(geometry["dimensions"], dtype=float)
    dividers = np.asarray(geometry["zone_dividers"], dtype=float)
    if (geometry["status"] != "provisional_simulation_geometry" or geometry["unit"] != "m"
            or geometry["axes"] != ["left_to_right", "front_to_rear", "floor_to_roof"]
            or dimensions.shape != (3,) or dividers.shape != (2,)
            or not np.isfinite(dimensions).all() or not np.isfinite(dividers).all()
            or np.any(dimensions <= 0) or np.any(dividers <= 0) or np.any(dividers >= dimensions[:2])):
        raise ValueError("Invalid cabin coordinate system or dimensions")
    if any(set(geometry[key]) != set(ZONE_ORDER)
           for key in ("seats", "representative_points", "source_candidates")):
        raise ValueError("Geometry must define all four zones")
    zones = CarZones(tuple(dimensions), tuple(dividers), ())
    representatives = tuple(zones.check_point(geometry["representative_points"][z]) for z in ZONE_ORDER)
    zones = CarZones(zones.dimensions, zones.dividers, representatives)
    seats = tuple(zones.check_point(geometry["seats"][z]) for z in ZONE_ORDER)
    candidates = tuple(tuple(zones.check_point(p) for p in geometry["source_candidates"][z])
                       for z in ZONE_ORDER)
    for zone, seat, point, points in zip(ZONE_ORDER, seats, representatives, candidates):
        if not points or any(zones.zone_id(p) != zone for p in (seat, point, *points)):
            raise ValueError(f"Invalid positions for zone {zone}")
    all_candidates = tuple(p for group in candidates for p in group)
    if len(set(all_candidates)) != len(all_candidates):
        raise ValueError("Source candidates cannot share a position")
    if set(arrays["microphones"]) != set(MIC_IDS) or set(arrays["layouts"]) != set(map(str, LAYOUT_SIZES)):
        raise ValueError("Expected microphones M0–M9 and layouts 8/6/4/3/2")
    microphones = tuple(zones.check_point(arrays["microphones"][mic]) for mic in MIC_IDS)
    if len(set(microphones)) != len(MIC_IDS) or set(microphones).intersection(
        all_candidates + representatives + seats
    ):
        raise ValueError("Microphones must have distinct positions away from seat and source points")
    if any(not isinstance(identifier, str) or not identifier.strip()
           for identifier in (geometry["room_id"], arrays["family_id"])):
        raise ValueError("Room and array family IDs must be nonempty")
    layouts = []
    for size in LAYOUT_SIZES:
        entry = arrays["layouts"][str(size)]
        ids = tuple(entry["channel_ids"])
        if len(ids) != size or len(set(ids)) != size or not all(i in MIC_IDS for i in ids):
            raise ValueError(f"Invalid {size}-microphone layout")
        if entry["reference_id"] not in ids:
            raise ValueError(f"Invalid reference for {size}-microphone layout")
        layouts.append(ArrayLayout(f"{arrays['family_id']}_{size}", ids,
                                   tuple(microphones[MIC_IDS.index(mic)] for mic in ids),
                                   ids.index(entry["reference_id"])))
    return CarGeometry(geometry["room_id"], zones, seats, candidates, microphones, tuple(layouts))
