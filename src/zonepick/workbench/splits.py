"""参数化 train/val/test 数据划分与冻结 manifest。

公平性设计：
- speaker-disjoint：LibriSpeech 按说话人 ID 划分，训练/测试说话人不重叠；
- session-disjoint：dEchorate 按房间、McVAMPIRE 按说话人座位划分，RIR 不跨集合复用；
- 比例是参数（默认 70/15/15），用户可自行调整；划分由固定种子决定，可复现；
- manifest 一旦写入即为冻结测试集：训练配置只允许引用 train/val 路径，
  test 路径不进入训练命名空间（由测试断言守护）。
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re

import numpy as np


@dataclass
class SplitConfig:
    """划分参数，全部可外部调节。"""

    train_ratio: float = 0.70
    val_ratio: float = 0.15
    test_ratio: float = 0.15
    seed: int = 42
    strategy: str = "group"          # group（按说话人/会话）| file（仅用于无分组信息的数据）
    librispeech_speaker_pattern: str = r"(\d+)"  # 从 FLAC 路径提取说话人 ID

    def validate(self):
        total = self.train_ratio + self.val_ratio + self.test_ratio
        if not np.isclose(total, 1.0, atol=1e-9):
            raise ValueError(f"划分比例之和须为 1.0，当前为 {total}")
        if min(self.train_ratio, self.val_ratio, self.test_ratio) < 0:
            raise ValueError("划分比例不可为负")
        if self.strategy not in ("group", "file"):
            raise ValueError("strategy 须为 group 或 file")


@dataclass
class SplitManifest:
    """冻结的划分结果。"""

    config: dict
    created_at: str
    splits: dict = field(default_factory=dict)   # {split: {group: [relative paths]}}

    def to_json(self):
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def write(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json() + "\n", encoding="utf-8")
        return path

    @classmethod
    def read(cls, path):
        return cls(**json.loads(Path(path).read_text(encoding="utf-8")))

    def paths_for(self, split):
        """展平某集合的全部相对路径。"""
        return [p for paths in self.splits.get(split, {}).values() for p in paths]


def _group_key(path, strategy, pattern):
    """从相对路径提取分组键（说话人/会话），保证同组不跨集合。"""
    if strategy == "file":
        return str(path)
    match = re.search(pattern, str(path))
    return match.group(1) if match else str(path)


def build_split(entries, root, config):
    """对一组相对路径做 group-disjoint 划分，返回 SplitManifest。

    entries: 相对路径列表；root: 数据根目录（用于 manifest 记录）。
    """
    config.validate()
    groups = {}
    for entry in entries:
        key = _group_key(entry, config.strategy, config.librispeech_speaker_pattern)
        groups.setdefault(key, []).append(str(entry))
    keys = sorted(groups)
    rng = np.random.default_rng(config.seed)
    order = rng.permutation(len(keys))
    n = len(keys)
    n_train = int(round(n * config.train_ratio))
    n_val = int(round(n * config.val_ratio))
    # 保证 test/val 至少各有一组（当组数允许时）。
    if n >= 3:
        n_train = min(max(n_train, 1), n - 2)
        n_val = min(max(n_val, 1), n - n_train - 1)
    assignment = {}
    for position, key_index in enumerate(order):
        split = "train" if position < n_train else (
            "val" if position < n_train + n_val else "test")
        assignment[keys[key_index]] = split
    splits = {name: {} for name in ("train", "val", "test")}
    for key, paths in groups.items():
        splits[assignment[key]][key] = sorted(paths)
    return SplitManifest(
        config=asdict(config),
        created_at=datetime.now(timezone.utc).isoformat(),
        splits=splits,
    )


def build_librispeech_split(root, config=None):
    """扫描 LibriSpeech 的 FLAC，按说话人做 train/val/test 划分。"""
    config = config or SplitConfig()
    root = Path(root)
    entries = [p.relative_to(root) for p in sorted(root.rglob("*.flac"))]
    if not entries:
        raise ValueError(f"未找到 LibriSpeech FLAC: {root}")
    return build_split(entries, root, config)


def assert_no_test_leak(manifest, train_entries):
    """防泄漏断言：训练条目不得出现在 test 集合中。"""
    test = set(manifest.paths_for("test"))
    leaked = test.intersection(str(e) for e in train_entries)
    if leaked:
        raise AssertionError(f"训练集包含 test 条目: {sorted(leaked)[:5]}")
    return True
